"""Tests for the Phase 6a historical loader."""

from __future__ import annotations

import bz2
import io
import json
import tarfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from algobet_common.schemas import MarketData, Venue
from ingestion.historical_loader import (
    decode_mcm_line,
    iter_archive_from_directory,
    iter_mcm_lines_from_tar,
    load_archive,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _flush_redis() -> Iterator[None]:
    """Override the module-level Redis-flushing fixture: these tests don't need it."""
    yield


def _make_mcm_line(
    *,
    publish_time_ms: int,
    market_id: str = "1.234",
    selection_id: int = 101,
    best_back_price: float = 1.50,
    best_back_size: float = 25.0,
    best_lay_price: float = 1.52,
    best_lay_size: float = 30.0,
    last_trade: float | None = 1.51,
) -> bytes:
    payload = {
        "op": "mcm",
        "pt": publish_time_ms,
        "mc": [
            {
                "id": market_id,
                "rc": [
                    {
                        "id": selection_id,
                        "batb": [[0, best_back_price, best_back_size]],
                        "batl": [[0, best_lay_price, best_lay_size]],
                        **({"ltp": last_trade} if last_trade is not None else {}),
                    }
                ],
            }
        ],
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


def _write_synthetic_tar(path: Path, n_ticks: int, *, start_ms: int = 1_744_980_000_000) -> None:
    """Write a TAR containing one bz2 NDJSON file with `n_ticks` mcm messages."""
    # One message per minute; deterministic timestamps.
    lines: list[bytes] = []
    for i in range(n_ticks):
        lines.append(
            _make_mcm_line(
                publish_time_ms=start_ms + i * 60_000,
                best_back_price=1.40 + (i % 10) * 0.01,
                last_trade=1.41 + (i % 10) * 0.01,
            )
        )
    raw = b"".join(lines)
    compressed = bz2.compress(raw)

    with tarfile.open(path, mode="w") as tar:
        info = tarfile.TarInfo(name="market.1.234.bz2")
        info.size = len(compressed)
        tar.addfile(info, io.BytesIO(compressed))


# ---------------------------------------------------------------------------
# decode_mcm_line — pure unit tests
# ---------------------------------------------------------------------------


def test_decode_mcm_line_maps_runner_change_to_market_data() -> None:
    line = _make_mcm_line(publish_time_ms=1_744_979_200_000)

    messages = decode_mcm_line(line)

    assert len(messages) == 1
    msg = messages[0]
    assert msg.venue == Venue.BETFAIR
    assert msg.market_id == "1.234:101"
    assert msg.timestamp == datetime.fromtimestamp(1_744_979_200, tz=UTC)
    assert msg.bids == [(Decimal("1.50"), Decimal("25.0"))]
    assert msg.asks == [(Decimal("1.52"), Decimal("30.0"))]
    assert msg.last_trade == Decimal("1.51")


def test_decode_mcm_line_accepts_str_input() -> None:
    line = _make_mcm_line(publish_time_ms=1_744_979_200_000).decode("utf-8")
    assert len(decode_mcm_line(line)) == 1


def test_decode_mcm_line_returns_empty_for_non_mcm_op() -> None:
    heartbeat = json.dumps({"op": "connection", "connectionId": "abc"}).encode("utf-8")
    assert decode_mcm_line(heartbeat) == []


def test_decode_mcm_line_returns_empty_for_malformed_json() -> None:
    assert decode_mcm_line(b"{not json}") == []


def test_decode_mcm_line_skips_cleared_levels_size_zero() -> None:
    payload = {
        "op": "mcm",
        "pt": 1_744_979_200_000,
        "mc": [
            {
                "id": "1.234",
                "rc": [
                    {
                        "id": 101,
                        "batb": [[0, 1.50, 0.0]],  # cleared
                        "batl": [[0, 1.52, 30.0]],
                    }
                ],
            }
        ],
    }
    messages = decode_mcm_line(json.dumps(payload).encode("utf-8"))
    assert messages[0].bids == []
    assert messages[0].asks == [(Decimal("1.52"), Decimal("30.0"))]


def test_decode_mcm_line_handles_missing_ltp() -> None:
    messages = decode_mcm_line(_make_mcm_line(publish_time_ms=1, last_trade=None))
    assert messages[0].last_trade is None


def test_decode_mcm_line_emits_one_message_per_runner() -> None:
    payload = {
        "op": "mcm",
        "pt": 1_744_979_200_000,
        "mc": [
            {
                "id": "1.234",
                "rc": [
                    {"id": 101, "batb": [[0, 1.5, 10]], "batl": [[0, 1.52, 12]]},
                    {"id": 202, "batb": [[0, 3.0, 5]], "batl": [[0, 3.1, 6]]},
                ],
            }
        ],
    }
    messages = decode_mcm_line(json.dumps(payload))
    assert [m.market_id for m in messages] == ["1.234:101", "1.234:202"]


# ---------------------------------------------------------------------------
# TAR iteration — unit test with tiny fixture
# ---------------------------------------------------------------------------


def test_iter_mcm_lines_from_tar_reads_bz2_member(tmp_path: Path) -> None:
    tar_path = tmp_path / "sample.tar"
    _write_synthetic_tar(tar_path, n_ticks=3)

    lines = list(iter_mcm_lines_from_tar(tar_path))
    assert len(lines) == 3
    for line in lines:
        payload = json.loads(line)
        assert payload["op"] == "mcm"


def test_iter_archive_from_directory_decodes_three_ticks(tmp_path: Path) -> None:
    _write_synthetic_tar(tmp_path / "a.tar", n_ticks=3)

    ticks = list(iter_archive_from_directory(tmp_path))
    assert len(ticks) == 3
    assert all(isinstance(t, MarketData) for t in ticks)
    # Timestamps strictly increasing.
    stamps = [t.timestamp for t in ticks]
    assert stamps == sorted(stamps)


# ---------------------------------------------------------------------------
# XRANGE mode — uses fakeredis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_archive_redis_xrange_yields_all_entries() -> None:
    fakeredis = pytest.importorskip("fakeredis")

    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        # Seed 5 MarketData entries in XADD order.
        base = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
        for i in range(5):
            msg = MarketData(
                venue=Venue.BETFAIR,
                market_id=f"1.234:10{i}",
                timestamp=base + timedelta(seconds=i),
                bids=[(Decimal("1.50"), Decimal("10"))],
                asks=[(Decimal("1.52"), Decimal("12"))],
                last_trade=Decimal("1.51"),
            )
            await client.xadd("market.data", {"json": msg.model_dump_json()})

        collected: list[MarketData] = []

        class _CaptureConn:
            async def fetch(self, _sql: str, *args: Any) -> list[object]:
                # Build a MarketData echo so the test asserts round-trip shape.
                collected.append(
                    MarketData(
                        venue=Venue(args[0]),
                        market_id=str(args[1]),
                        timestamp=args[2],
                        bids=[(Decimal(p), Decimal(s)) for p, s in json.loads(str(args[3]))],
                        asks=[(Decimal(p), Decimal(s)) for p, s in json.loads(str(args[4]))],
                        last_trade=args[5],
                    )
                )
                return [1]  # pretend one row inserted

        inserted = await load_archive(
            "redis_xrange",
            conn=_CaptureConn(),
            venue="betfair",
            redis_client=client,
            stream="market.data",
            batch_size=2,  # force multiple flushes
        )

        assert inserted == 5
        assert [t.market_id for t in collected] == [
            "1.234:100",
            "1.234:101",
            "1.234:102",
            "1.234:103",
            "1.234:104",
        ]
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# load_archive — argument validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_archive_rejects_unknown_source() -> None:
    class _NoopConn:
        async def fetch(self, _sql: str, *_args: object) -> list[object]:
            return []

    with pytest.raises(ValueError, match="unknown source"):
        await load_archive("unsupported", conn=_NoopConn())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_load_archive_rejects_non_uk_venue() -> None:
    class _NoopConn:
        async def fetch(self, _sql: str, *_args: object) -> list[object]:
            return []

    with pytest.raises(ValueError, match="unsupported venue"):
        await load_archive(
            "betfair_tar",
            conn=_NoopConn(),
            venue="polymarket",
            archive_dir="/tmp/doesnotmatter",
        )


@pytest.mark.asyncio
async def test_load_archive_requires_archive_dir_for_tar_mode() -> None:
    class _NoopConn:
        async def fetch(self, _sql: str, *_args: object) -> list[object]:
            return []

    with pytest.raises(ValueError, match="archive_dir"):
        await load_archive("betfair_tar", conn=_NoopConn())


# ---------------------------------------------------------------------------
# Integration: round-trip via real Postgres
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_load_archive_roundtrip_100_ticks(
    postgres_dsn: str, tmp_path: Path, require_postgres: None
) -> None:
    """Done-when from the plan: 100 synthetic ticks load; second load = 0 new rows."""
    import asyncpg

    from scripts.migrate import apply_migrations

    # Ensure schema is up to date.
    await apply_migrations(postgres_dsn, Path("scripts/db/migrations"))

    _write_synthetic_tar(tmp_path / "fixture.tar", n_ticks=100)

    conn = await asyncpg.connect(postgres_dsn)
    try:
        # Clean any prior runs of this fixture.
        await conn.execute("DELETE FROM market_data_archive WHERE market_id LIKE '1.234:%'")

        inserted_first = await load_archive(
            "betfair_tar",
            conn=conn,
            venue="betfair",
            archive_dir=tmp_path,
            batch_size=25,
        )
        assert inserted_first == 100

        count = await conn.fetchval(
            "SELECT count(*) FROM market_data_archive WHERE market_id LIKE '1.234:%'"
        )
        assert count == 100

        # Second load is idempotent.
        inserted_second = await load_archive(
            "betfair_tar",
            conn=conn,
            venue="betfair",
            archive_dir=tmp_path,
            batch_size=25,
        )
        assert inserted_second == 0

        count_after = await conn.fetchval(
            "SELECT count(*) FROM market_data_archive WHERE market_id LIKE '1.234:%'"
        )
        assert count_after == 100

        # Cleanup so repeated runs don't accumulate.
        await conn.execute("DELETE FROM market_data_archive WHERE market_id LIKE '1.234:%'")
    finally:
        await conn.close()

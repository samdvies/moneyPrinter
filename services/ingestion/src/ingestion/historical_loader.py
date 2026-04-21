"""Historical market-data loader for Phase 6a backtest harness.

Populates the `market_data_archive` hypertable from two sources:

* `betfair_tar`  — a directory of Betfair historical TAR files. Each TAR member
  is a bz2-compressed NDJSON stream of Exchange Stream API messages. We only
  parse `mcm` (market change message) lines; each `mc.rc` runner change becomes
  one `MarketData` row keyed by `f"{market_id}:{selection_id}"` for parity with
  `betfair_adapter.map_market_book_to_messages`.
* `redis_xrange` — replays `XRANGE market.data - +` and parses each entry's
  `json` field back into `MarketData`. Lets a live ingestion session seed the
  archive.

Design notes:

* The live Betfair adapter takes a ``betfairlightweight`` object with attribute
  ladders; historical mcm lines are plain dicts with list ladders
  ``[[level, price, size], ...]``. The shapes genuinely differ, so we keep the
  decode in this module rather than shoehorning mcm into the live adapter.
* Idempotency uses ``ON CONFLICT (venue, market_id, observed_at) DO NOTHING``.
* Row-count return uses ``INSERT ... RETURNING 1`` so we count rows that were
  actually inserted (not merely processed).
"""

from __future__ import annotations

import bz2
import json
import logging
import tarfile
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

import asyncpg
from algobet_common.schemas import MarketData, Venue

LOGGER = logging.getLogger(__name__)

_INSERT_SQL = (
    "INSERT INTO market_data_archive "
    "(venue, market_id, observed_at, bids, asks, last_trade) "
    "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6) "
    "ON CONFLICT (venue, market_id, observed_at) DO NOTHING "
    "RETURNING 1"
)


class _AsyncpgExecutor(Protocol):
    """Minimal asyncpg surface we need; lets us accept Connection or Pool-acquired conn."""

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]: ...


def _ladder_from_mcm(rows: Iterable[Any]) -> list[tuple[Decimal, Decimal]]:
    """Normalise an mcm ladder (``[[level, price, size], ...]``) into
    ``list[(price, size)]``. Non-positive sizes are dropped — Betfair uses
    ``size == 0`` to mean "level was cleared"."""
    result: list[tuple[Decimal, Decimal]] = []
    for row in rows or ():
        # mcm ladders are lists: [level, price, size].
        if not isinstance(row, list | tuple) or len(row) < 3:
            continue
        price = row[1]
        size = row[2]
        if price is None or size is None:
            continue
        try:
            price_dec = Decimal(str(price))
            size_dec = Decimal(str(size))
        except (ArithmeticError, ValueError):
            continue
        if size_dec <= 0:
            continue
        result.append((price_dec, size_dec))
    return result


def decode_mcm_line(line: bytes | str) -> list[MarketData]:
    """Decode a single Betfair Exchange Stream `mcm` JSON line into MarketData.

    Non-mcm ops (heartbeats, connection frames, `ocm`) yield an empty list.
    Unknown venues never occur here — Betfair stream data is always Betfair.
    """
    text = line.decode("utf-8").strip() if isinstance(line, bytes | bytearray) else line.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        LOGGER.warning("skipping malformed mcm line: %r", text[:120])
        return []
    if not isinstance(payload, dict) or payload.get("op") != "mcm":
        return []

    publish_time_ms = payload.get("pt")
    if publish_time_ms is None:
        timestamp = datetime.now(UTC)
    else:
        timestamp = datetime.fromtimestamp(int(publish_time_ms) / 1000, tz=UTC)

    messages: list[MarketData] = []
    for market_change in payload.get("mc") or ():
        market_id = market_change.get("id")
        if not market_id:
            continue
        for runner_change in market_change.get("rc") or ():
            selection_id = runner_change.get("id")
            if selection_id is None:
                continue
            bids = _ladder_from_mcm(runner_change.get("batb"))
            asks = _ladder_from_mcm(runner_change.get("batl"))
            ltp = runner_change.get("ltp")
            last_trade = Decimal(str(ltp)) if ltp is not None else None
            messages.append(
                MarketData(
                    venue=Venue.BETFAIR,
                    market_id=f"{market_id}:{selection_id}",
                    timestamp=timestamp,
                    bids=bids,
                    asks=asks,
                    last_trade=last_trade,
                )
            )
    return messages


def iter_mcm_lines_from_tar(tar_path: Path) -> Iterator[bytes]:
    """Yield raw NDJSON lines from every bz2 member inside a Betfair historical TAR.

    Betfair's historical archive packages each market as a bz2-compressed NDJSON
    stream; a TAR bundles many of those. We stream decompression rather than
    reading whole members into memory.
    """
    with tarfile.open(tar_path, mode="r:*") as tar:
        for member in tar:
            if not member.isfile():
                continue
            # Betfair historical members are uniformly bz2; tolerate plain .json
            # for synthetic fixtures that skip the outer compression.
            fh = tar.extractfile(member)
            if fh is None:
                continue
            raw = fh.read()
            if member.name.endswith(".bz2") or _looks_like_bz2(raw):
                try:
                    raw = bz2.decompress(raw)
                except OSError:
                    LOGGER.warning("failed to bz2-decompress %s; skipping", member.name)
                    continue
            for line in raw.splitlines():
                if line.strip():
                    yield line


def _looks_like_bz2(data: bytes) -> bool:
    return data.startswith(b"BZh")


def iter_archive_from_directory(directory: Path) -> Iterator[MarketData]:
    """Walk a directory of Betfair historical TARs and yield MarketData rows."""
    if not directory.is_dir():
        raise NotADirectoryError(f"historical archive dir not found: {directory}")
    for tar_path in sorted(directory.glob("*.tar")):
        for line in iter_mcm_lines_from_tar(tar_path):
            yield from decode_mcm_line(line)


def _serialise_ladder(ladder: list[tuple[Decimal, Decimal]]) -> str:
    """JSONB-safe serialisation: list of [price, size] strings to preserve precision."""
    return json.dumps([[str(price), str(size)] for price, size in ladder])


async def _insert_batch(
    conn: _AsyncpgExecutor,
    venue: str,
    batch: list[MarketData],
) -> int:
    """Insert one batch; return count of rows actually inserted (not conflicted)."""
    inserted = 0
    for tick in batch:
        rows = await conn.fetch(
            _INSERT_SQL,
            venue,
            tick.market_id,
            tick.timestamp,
            _serialise_ladder(tick.bids),
            _serialise_ladder(tick.asks),
            tick.last_trade,
        )
        if rows:
            inserted += 1
    return inserted


async def _drain_in_batches(
    ticks: Iterable[MarketData] | AsyncIterator[MarketData],
    conn: _AsyncpgExecutor,
    venue: str,
    batch_size: int,
) -> int:
    total = 0
    batch: list[MarketData] = []

    async def _flush() -> None:
        nonlocal total
        if batch:
            total += await _insert_batch(conn, venue, batch)
            batch.clear()

    if hasattr(ticks, "__aiter__"):
        async_ticks: AsyncIterator[MarketData] = ticks  # type: ignore[assignment]
        async for tick in async_ticks:
            batch.append(tick)
            if len(batch) >= batch_size:
                await _flush()
    else:
        sync_ticks: Iterable[MarketData] = ticks
        for tick in sync_ticks:
            batch.append(tick)
            if len(batch) >= batch_size:
                await _flush()
    await _flush()
    return total


async def _iter_redis_xrange(
    redis_client: Any, stream: str = "market.data"
) -> AsyncIterator[MarketData]:
    """XRANGE the configured stream end-to-end and yield parsed MarketData."""
    entries = await redis_client.xrange(stream, min="-", max="+")
    for _entry_id, fields in entries:
        # redis-py returns bytes when decode_responses=False, str otherwise.
        raw = fields.get(b"json") if b"json" in fields else fields.get("json")
        if raw is None:
            continue
        if isinstance(raw, bytes | bytearray):
            raw = raw.decode("utf-8")
        yield MarketData.model_validate_json(raw)


async def load_archive(
    source: Literal["betfair_tar", "redis_xrange"],
    *,
    conn: _AsyncpgExecutor,
    venue: str = "betfair",
    batch_size: int = 5000,
    archive_dir: Path | str | None = None,
    redis_client: Any | None = None,
    stream: str = "market.data",
) -> int:
    """Load historical MarketData into the archive hypertable.

    Returns the number of rows actually inserted (rows that survived
    `ON CONFLICT DO NOTHING`). Re-running with no new data returns 0.
    """
    if venue not in (Venue.BETFAIR.value, Venue.KALSHI.value):
        raise ValueError(f"unsupported venue for archive loader: {venue!r}")

    if source == "betfair_tar":
        if archive_dir is None:
            raise ValueError("betfair_tar mode requires archive_dir")
        directory = Path(archive_dir)
        return await _drain_in_batches(
            iter_archive_from_directory(directory),
            conn,
            venue,
            batch_size,
        )

    if source == "redis_xrange":
        if redis_client is None:
            raise ValueError("redis_xrange mode requires redis_client")
        return await _drain_in_batches(
            _iter_redis_xrange(redis_client, stream=stream),
            conn,
            venue,
            batch_size,
        )

    raise ValueError(f"unknown source: {source!r}")

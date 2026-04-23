import json
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

from scripts.migrate import apply_migrations, load_migrations

pytestmark = pytest.mark.integration


def test_load_migrations_returns_sorted_by_version() -> None:
    migrations_dir = Path("scripts/db/migrations")
    migrations = load_migrations(migrations_dir)
    assert [m.version for m in migrations] == ["0001", "0002", "0003", "0004", "0005", "0006"]
    assert "timescaledb" in migrations[0].sql.lower()


@pytest.mark.asyncio
async def test_apply_migrations_creates_strategies_table(postgres_dsn: str) -> None:
    try:
        conn_check = await asyncpg.connect(postgres_dsn)
    except OSError as exc:
        pytest.skip(f"Postgres unavailable for integration test: {exc}")
    await conn_check.close()

    await apply_migrations(postgres_dsn, Path("scripts/db/migrations"))

    conn = await asyncpg.connect(postgres_dsn)
    try:
        row = await conn.fetchrow("SELECT to_regclass('strategies') AS tbl")
        assert row["tbl"] == "strategies"

        versions = await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
        assert [r["version"] for r in versions] == ["0001", "0002", "0003", "0004", "0005", "0006"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_migration_0005_market_data_archive_hypertable(postgres_dsn: str) -> None:
    """Migration 0005 must land `market_data_archive` as a Timescale hypertable
    with PK-based idempotency for re-loaded TAR files."""
    try:
        conn_check = await asyncpg.connect(postgres_dsn)
    except OSError as exc:
        pytest.skip(f"Postgres unavailable for integration test: {exc}")
    await conn_check.close()

    await apply_migrations(postgres_dsn, Path("scripts/db/migrations"))

    conn = await asyncpg.connect(postgres_dsn)
    try:
        # Table exists.
        tbl = await conn.fetchval("SELECT to_regclass('market_data_archive')")
        assert tbl == "market_data_archive"

        # Hypertable metadata present.
        ht = await conn.fetchval(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'market_data_archive'"
        )
        assert ht == "market_data_archive"

        # Replay index present.
        idx = await conn.fetchval(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'market_data_archive' "
            "  AND indexname = 'idx_market_data_archive_replay'"
        )
        assert idx == "idx_market_data_archive_replay"

        # Round-trip a row.
        ts = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
        bids = json.dumps([["1.50", "25.00"], ["1.49", "10.00"]])
        asks = json.dumps([["1.52", "30.00"]])
        await conn.execute("DELETE FROM market_data_archive WHERE market_id = 'test-0005'")
        await conn.execute(
            "INSERT INTO market_data_archive "
            "(venue, market_id, observed_at, bids, asks, last_trade) "
            "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6)",
            "betfair",
            "test-0005",
            ts,
            bids,
            asks,
            "1.51",
        )

        row = await conn.fetchrow(
            "SELECT venue, market_id, observed_at, bids, asks, last_trade "
            "FROM market_data_archive WHERE market_id = 'test-0005'"
        )
        assert row is not None
        assert row["venue"] == "betfair"
        assert row["market_id"] == "test-0005"
        assert row["observed_at"] == ts
        assert json.loads(row["bids"]) == [["1.50", "25.00"], ["1.49", "10.00"]]
        assert json.loads(row["asks"]) == [["1.52", "30.00"]]
        assert str(row["last_trade"]) == "1.5100"

        # Idempotent re-load: ON CONFLICT DO NOTHING is a no-op on duplicate PK.
        status = await conn.execute(
            "INSERT INTO market_data_archive "
            "(venue, market_id, observed_at, bids, asks, last_trade) "
            "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6) "
            "ON CONFLICT (venue, market_id, observed_at) DO NOTHING",
            "betfair",
            "test-0005",
            ts,
            bids,
            asks,
            "1.51",
        )
        # asyncpg returns the command tag; exactly 0 rows inserted on conflict.
        assert status == "INSERT 0 0"

        count = await conn.fetchval(
            "SELECT count(*) FROM market_data_archive WHERE market_id = 'test-0005'"
        )
        assert count == 1

        # Venue CHECK constraint rejects anything outside (betfair, kalshi).
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO market_data_archive "
                "(venue, market_id, observed_at, bids, asks) "
                "VALUES ('polymarket', 'test-0005-bad', $1, '[]'::jsonb, '[]'::jsonb)",
                ts,
            )

        await conn.execute("DELETE FROM market_data_archive WHERE market_id = 'test-0005'")
    finally:
        await conn.close()

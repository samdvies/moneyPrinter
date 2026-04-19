from pathlib import Path

import asyncpg
import pytest

from scripts.migrate import apply_migrations, load_migrations

pytestmark = pytest.mark.integration


def test_load_migrations_returns_sorted_by_version() -> None:
    migrations_dir = Path("scripts/db/migrations")
    migrations = load_migrations(migrations_dir)
    assert [m.version for m in migrations] == ["0001", "0002", "0003"]
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
        assert [r["version"] for r in versions] == ["0001", "0002", "0003"]
    finally:
        await conn.close()

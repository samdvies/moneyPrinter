import asyncpg
import pytest
from algobet_common.db import Database

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_database_pool_roundtrip(postgres_dsn: str) -> None:
    try:
        conn_check = await asyncpg.connect(postgres_dsn)
    except Exception as exc:
        pytest.skip(f"Postgres unavailable for integration test: {exc}")
    else:
        await conn_check.close()

    db = Database(postgres_dsn)
    await db.connect()
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 AS value")
            assert row["value"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_database_acquire_before_connect_raises(postgres_dsn: str) -> None:
    db = Database(postgres_dsn)
    with pytest.raises(RuntimeError):
        async with db.acquire():
            pass

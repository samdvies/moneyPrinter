import pytest
from algobet_common.db import Database


@pytest.mark.asyncio
async def test_database_pool_roundtrip(postgres_dsn: str) -> None:
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

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest


@pytest.fixture
def postgres_dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "algobet")
    password = os.environ.get("POSTGRES_PASSWORD", "devpassword")
    db = os.environ.get("POSTGRES_DB", "algobet")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture(autouse=True)
async def _reset_db(postgres_dsn: str) -> AsyncIterator[None]:
    conn = await asyncpg.connect(postgres_dsn)
    try:
        await conn.execute("""
            DROP TABLE IF EXISTS orders CASCADE;
            DROP TABLE IF EXISTS strategy_runs CASCADE;
            DROP TABLE IF EXISTS strategies CASCADE;
            DROP TABLE IF EXISTS schema_migrations CASCADE;
        """)
    finally:
        await conn.close()
    yield

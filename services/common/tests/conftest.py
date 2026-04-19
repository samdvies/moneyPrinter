import os
from collections.abc import AsyncIterator
from typing import Any, cast

import asyncpg
import pytest


@pytest.fixture
def postgres_dsn() -> str:
    # Default to 127.0.0.1 — on Windows `localhost` resolves to IPv6 ::1 first
    # and a ~21s TCP timeout per connection fires before falling back to IPv4.
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "algobet")
    password = os.environ.get("POSTGRES_PASSWORD", "devpassword")
    db = os.environ.get("POSTGRES_DB", "algobet")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture
async def require_postgres(postgres_dsn: str) -> AsyncIterator[None]:
    """Skip test when Postgres integration dependency is unavailable."""
    try:
        conn = await asyncpg.connect(postgres_dsn)
    except Exception as exc:
        pytest.skip(f"Postgres unavailable for integration test: {exc}")
    try:
        yield
    finally:
        await conn.close()


@pytest.fixture
def redis_url() -> str:
    # Default to 127.0.0.1 — on Windows `localhost` resolves to IPv6 ::1 first
    # and a ~21s TCP timeout per connection fires before falling back to IPv4.
    host = os.environ.get("REDIS_HOST", "127.0.0.1")
    port = os.environ.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}/15"  # DB 15 = isolated test db


@pytest.fixture
async def _flush_redis(redis_url: str) -> AsyncIterator[None]:
    import redis.asyncio as redis

    client = redis.from_url(redis_url)
    try:
        await client.flushdb()
    except Exception as exc:
        pytest.skip(f"Redis unavailable for integration test: {exc}")
    finally:
        await client.aclose()
    yield


@pytest.fixture
async def require_redis(redis_url: str) -> AsyncIterator[None]:
    """Skip test when Redis integration dependency is unavailable."""
    import redis.asyncio as redis

    client = cast(Any, redis.from_url(redis_url))
    try:
        await client.execute_command("PING")
    except Exception as exc:
        pytest.skip(f"Redis unavailable for integration test: {exc}")
    finally:
        await client.aclose()
    yield

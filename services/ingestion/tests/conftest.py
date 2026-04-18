import os
from collections.abc import AsyncIterator

import pytest


@pytest.fixture
def redis_url() -> str:
    host = os.environ.get("REDIS_HOST", "localhost")
    port = os.environ.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}/15"


@pytest.fixture(autouse=True)
async def _flush_redis(redis_url: str) -> AsyncIterator[None]:
    import redis.asyncio as redis

    client = redis.from_url(redis_url)
    try:
        await client.flushdb()
    finally:
        await client.aclose()
    yield

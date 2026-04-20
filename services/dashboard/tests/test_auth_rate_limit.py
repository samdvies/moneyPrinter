"""Integration tests for the fixed-window Redis rate limiter."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import redis.asyncio as redis
from dashboard.auth.rate_limit import check_and_increment

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def r(redis_url: str, require_redis: None, _flush_redis: None) -> AsyncIterator[redis.Redis]:
    client = redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


def _key(tag: str = "") -> str:
    return f"dashboard:test:rl:{tag}:{uuid.uuid4().hex[:8]}"


async def test_increment_under_limit_returns_true(r: redis.Redis) -> None:
    k = _key("under")
    for _ in range(5):
        assert await check_and_increment(r, key=k, max_attempts=10, window_seconds=60) is True


async def test_increment_at_limit_returns_false(r: redis.Redis) -> None:
    k = _key("at")
    for _ in range(3):
        assert await check_and_increment(r, key=k, max_attempts=3, window_seconds=60) is True
    # 4th attempt trips the limit.
    assert await check_and_increment(r, key=k, max_attempts=3, window_seconds=60) is False


@pytest.mark.slow
async def test_window_expiry_resets_counter(r: redis.Redis) -> None:
    k = _key("expiry")
    for _ in range(2):
        assert await check_and_increment(r, key=k, max_attempts=2, window_seconds=1) is True
    assert await check_and_increment(r, key=k, max_attempts=2, window_seconds=1) is False
    await asyncio.sleep(1.2)
    assert await check_and_increment(r, key=k, max_attempts=2, window_seconds=1) is True


async def test_concurrent_increments_race_safe(r: redis.Redis) -> None:
    k = _key("race")
    max_attempts = 10
    results = await asyncio.gather(
        *(
            check_and_increment(r, key=k, max_attempts=max_attempts, window_seconds=60)
            for _ in range(20)
        )
    )
    assert sum(1 for ok in results if ok) == max_attempts
    assert sum(1 for ok in results if not ok) == 10

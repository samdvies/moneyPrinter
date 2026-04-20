"""Fixed-window rate limiter backed by Redis.

`INCR` + `EXPIRE … NX` inside a transactional pipeline gives an atomic
increment-with-expiry-on-first-write primitive. Returns False iff the
resulting counter exceeds `max_attempts`. Window is fixed, not sliding —
simple and sufficient for login attempts where bursts are the threat.
"""

from __future__ import annotations

import redis.asyncio as redis


async def check_and_increment(
    r: redis.Redis,
    *,
    key: str,
    max_attempts: int,
    window_seconds: int,
) -> bool:
    async with r.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        results = await pipe.execute()
    count = int(results[0])
    return count <= max_attempts

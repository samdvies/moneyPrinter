"""FastAPI dependency callables for the dashboard service."""

from __future__ import annotations

import redis.asyncio as redis
from algobet_common.db import Database
from fastapi import Request


def get_db(request: Request) -> Database:
    return request.app.state.db  # type: ignore[no-any-return]


def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis  # type: ignore[no-any-return]

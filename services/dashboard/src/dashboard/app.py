"""FastAPI application factory for the dashboard service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from algobet_common.config import Settings
from algobet_common.db import Database
from fastapi import FastAPI

from .auth.routes import router as auth_router
from .routers.risk import router as risk_router
from .routers.strategies import router as strategies_router


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings(service_name="dashboard")
    db = Database(settings.postgres_dsn)
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)

    await db.connect()

    app.state.settings = settings
    app.state.db = db
    app.state.redis = redis_client

    try:
        yield
    finally:
        await db.close()
        await redis_client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Algo-Betting Dashboard", lifespan=_lifespan)
    app.include_router(auth_router)
    app.include_router(strategies_router)
    app.include_router(risk_router)
    return app

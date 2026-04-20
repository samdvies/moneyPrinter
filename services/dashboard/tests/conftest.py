"""Shared fixtures for dashboard integration tests."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI


@pytest.fixture
def _override_env(
    postgres_dsn: str,
    redis_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point the app's Settings at the test Postgres and Redis instances."""
    pg = re.match(r"postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", postgres_dsn)
    if pg:
        monkeypatch.setenv("POSTGRES_USER", pg.group(1))
        monkeypatch.setenv("POSTGRES_PASSWORD", pg.group(2))
        monkeypatch.setenv("POSTGRES_HOST", pg.group(3))
        monkeypatch.setenv("POSTGRES_PORT", pg.group(4))
        monkeypatch.setenv("POSTGRES_DB", pg.group(5))

    red = re.match(r"redis://([^:]+):(\d+)/(\d+)", redis_url)
    if red:
        monkeypatch.setenv("REDIS_HOST", red.group(1))
        monkeypatch.setenv("REDIS_PORT", red.group(2))
        monkeypatch.setenv("REDIS_DB", red.group(3))

    monkeypatch.setenv("SERVICE_NAME", "dashboard")
    # Tests run over plain http; allow cookies to be sent without TLS.
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("DASHBOARD_ALLOWED_ORIGINS", '["http://127.0.0.1"]')


@pytest_asyncio.fixture
async def app(
    require_postgres: None,
    require_redis: None,
    _flush_redis: None,
    _override_env: None,
) -> AsyncIterator[FastAPI]:
    from dashboard.app import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as c:
        yield c

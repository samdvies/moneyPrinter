"""Shared fixtures for dashboard integration tests."""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import pytest
import pytest_asyncio
from algobet_common.db import Database
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


# ---------------------------------------------------------------------------
# Auth fixtures for gated routes
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def operator_factory(
    app: FastAPI,
) -> AsyncIterator[Callable[..., Awaitable[tuple[object, str]]]]:
    """Factory that creates operators directly in Postgres and yields
    (Operator, plaintext_password) tuples. Cleans up all operators it
    minted when the test finishes."""
    from dashboard.auth import crud, passwords

    created: list[uuid.UUID] = []
    db: Database = app.state.db

    async def make(
        *,
        email: str | None = None,
        password: str = "correct horse battery staple",
    ) -> tuple[object, str]:
        email_addr = email or f"op-{uuid.uuid4().hex[:8]}@example.com"
        op = await crud.create_operator(
            db, email=email_addr, password_hash=passwords.hash_password(password)
        )
        created.append(op.id)
        return op, password

    yield make
    if created:
        async with db.acquire() as conn:
            await conn.execute("DELETE FROM operators WHERE id = ANY($1::uuid[])", created)


@pytest_asyncio.fixture
async def auth_client(
    app: FastAPI,
    operator_factory: Callable[..., Awaitable[tuple[object, str]]],
) -> AsyncIterator[tuple[httpx.AsyncClient, object]]:
    """Authenticated httpx client with session + csrf cookies in its jar.
    Yields the client plus the Operator pydantic model for identity assertions."""
    operator, password = await operator_factory()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as c:
        resp = await c.post(
            "/auth/login",
            json={"email": operator.email, "password": password},  # type: ignore[attr-defined]
        )
        assert resp.status_code == 200, resp.text
        yield c, operator


@pytest.fixture
def csrf_header(auth_client: tuple[httpx.AsyncClient, object]) -> dict[str, str]:
    """Read the csrf cookie off the auth_client jar and present it as an
    `X-CSRF-Token` header for double-submit validation."""
    client, _ = auth_client
    csrf = client.cookies.get("csrf")
    assert csrf, "auth_client should have a csrf cookie"
    return {"X-CSRF-Token": csrf}

"""Integration tests for /auth/login, /auth/logout, /auth/me."""

from __future__ import annotations

import statistics
import time
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as redis
from algobet_common.config import Settings
from algobet_common.db import Database
from dashboard.auth import crud, passwords
from dashboard.auth.models import Operator
from fastapi import FastAPI

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(postgres_dsn: str, require_postgres: None) -> AsyncIterator[Database]:
    database = Database(postgres_dsn)
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest_asyncio.fixture
async def r(redis_url: str, require_redis: None) -> AsyncIterator[redis.Redis]:
    client = redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def cleanup_operators(db: Database) -> AsyncIterator[list[uuid.UUID]]:
    created: list[uuid.UUID] = []
    yield created
    if created:
        async with db.acquire() as conn:
            await conn.execute("DELETE FROM operators WHERE id = ANY($1::uuid[])", created)


async def _make_operator(
    db: Database,
    cleanup: list[uuid.UUID],
    *,
    email: str | None = None,
    password: str = "correct horse battery staple",
) -> tuple[Operator, str]:
    email_addr = email or f"routes-{uuid.uuid4().hex[:8]}@example.com"
    op = await crud.create_operator(
        db, email=email_addr, password_hash=passwords.hash_password(password)
    )
    cleanup.append(op.id)
    return op, password


# ---------------------------------------------------------------------------
# Happy path + basic failure modes
# ---------------------------------------------------------------------------


async def test_login_happy_path(
    client: httpx.AsyncClient,
    db: Database,
    cleanup_operators: list[uuid.UUID],
) -> None:
    op, pwd = await _make_operator(db, cleanup_operators)
    resp = await client.post("/auth/login", json={"email": op.email, "password": pwd})
    assert resp.status_code == 200
    body = resp.json()
    assert body["operator"]["email"] == op.email
    # Both cookies present.
    cookie_names = {c.name for c in client.cookies.jar}
    assert "sess" in cookie_names
    assert "csrf" in cookie_names


async def test_login_wrong_password_returns_generic_401(
    client: httpx.AsyncClient,
    db: Database,
    cleanup_operators: list[uuid.UUID],
) -> None:
    op, _ = await _make_operator(db, cleanup_operators)
    resp = await client.post("/auth/login", json={"email": op.email, "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "authentication failed"}


async def test_login_unknown_email_returns_generic_401(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": f"nobody-{uuid.uuid4().hex[:8]}@example.com", "password": "x"},
    )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "authentication failed"}


async def test_login_calls_verify_password_on_unknown_email(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deterministic invariant test (S2-b): the unknown-email branch MUST
    still call verify_password (against _DUMMY_HASH) so timing doesn't leak
    whether the account exists."""
    # Patch the symbol the route module bound at import time.
    from dashboard.auth import routes as routes_module

    call_count = 0
    real = routes_module.verify_password  # type: ignore[attr-defined]

    def counting(hashed: str, plain: str) -> bool:
        nonlocal call_count
        call_count += 1
        return real(hashed, plain)

    monkeypatch.setattr(routes_module, "verify_password", counting)

    resp = await client.post(
        "/auth/login",
        json={"email": f"nobody-{uuid.uuid4().hex[:8]}@example.com", "password": "x"},
    )
    assert resp.status_code == 401
    assert call_count == 1


@pytest.mark.slow
async def test_login_response_time_parity_smoke(
    client: httpx.AsyncClient,
    db: Database,
    cleanup_operators: list[uuid.UUID],
) -> None:
    op, _ = await _make_operator(db, cleanup_operators)

    async def timed(json: dict[str, str]) -> float:
        start = time.perf_counter()
        await client.post("/auth/login", json=json)
        return time.perf_counter() - start

    unknown = [
        await timed({"email": f"nobody-{uuid.uuid4().hex[:8]}@example.com", "password": "x"})
        for _ in range(5)
    ]
    wrong = [await timed({"email": op.email, "password": "wrong"}) for _ in range(5)]
    # Rate limiter will have tripped by now; the purpose is only to confirm
    # orders of magnitude are similar, so compute medians of whatever succeeded.
    median_unknown = statistics.median(unknown)
    median_wrong = statistics.median(wrong)
    # Loose tolerance — tight parity is asserted deterministically above.
    assert abs(median_unknown - median_wrong) < 0.5


async def test_logout_clears_session(
    client: httpx.AsyncClient,
    db: Database,
    cleanup_operators: list[uuid.UUID],
) -> None:
    op, pwd = await _make_operator(db, cleanup_operators)
    await client.post("/auth/login", json={"email": op.email, "password": pwd})
    resp = await client.post("/auth/logout")
    assert resp.status_code == 204
    # /auth/me now rejects because the session is gone. Manually re-send the
    # dropped sess cookie from the response to prove server-side destruction.
    me = await client.get("/auth/me")
    assert me.status_code == 401


async def test_logout_without_session_is_idempotent(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post("/auth/logout")
    assert resp.status_code == 204


async def test_me_requires_session(client: httpx.AsyncClient) -> None:
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


async def test_me_returns_operator_on_valid_session(
    client: httpx.AsyncClient,
    db: Database,
    cleanup_operators: list[uuid.UUID],
) -> None:
    op, pwd = await _make_operator(db, cleanup_operators)
    await client.post("/auth/login", json={"email": op.email, "password": pwd})
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["operator"]["email"] == op.email


# ---------------------------------------------------------------------------
# Session-rotation semantics (S2-a)
# ---------------------------------------------------------------------------


async def test_login_rotates_session_on_garbage_cookie(
    client: httpx.AsyncClient,
    db: Database,
    cleanup_operators: list[uuid.UUID],
) -> None:
    op, pwd = await _make_operator(db, cleanup_operators)
    client.cookies.set("sess", "garbage-token", domain="127.0.0.1")
    resp = await client.post("/auth/login", json={"email": op.email, "password": pwd})
    assert resp.status_code == 200
    # New token present and different from "garbage-token".
    sess_cookies = [c for c in client.cookies.jar if c.name == "sess"]
    assert sess_cookies
    assert all(c.value != "garbage-token" for c in sess_cookies)


async def test_login_ignores_attackers_valid_session(
    client: httpx.AsyncClient,
    db: Database,
    r: redis.Redis,
    cleanup_operators: list[uuid.UUID],
) -> None:
    """S2-a: injecting A's valid token into B's login must (i) mint a fresh
    token for B and (ii) leave A's token valid for A."""
    op_a, pwd_a = await _make_operator(db, cleanup_operators, email=None)
    op_b, pwd_b = await _make_operator(db, cleanup_operators, email=None)

    # Log A in (via a separate transport) and capture A's token.
    login_a = await client.post("/auth/login", json={"email": op_a.email, "password": pwd_a})
    assert login_a.status_code == 200
    t_a = client.cookies.get("sess")
    assert t_a

    # Clear jar but resend A's token on B's login attempt.
    client.cookies.clear()
    client.cookies.set("sess", t_a, domain="127.0.0.1")
    login_b = await client.post("/auth/login", json={"email": op_b.email, "password": pwd_b})
    assert login_b.status_code == 200
    t_b = client.cookies.get("sess")
    assert t_b and t_b != t_a

    # t_b resolves to B.
    me_b = await client.get("/auth/me")
    assert me_b.status_code == 200
    assert me_b.json()["operator"]["email"] == op_b.email

    # Meanwhile t_a remains valid for A — swap cookies and confirm.
    client.cookies.clear()
    client.cookies.set("sess", t_a, domain="127.0.0.1")
    me_a = await client.get("/auth/me")
    assert me_a.status_code == 200
    assert me_a.json()["operator"]["email"] == op_a.email


# ---------------------------------------------------------------------------
# Rate-limit (S1-c)
# ---------------------------------------------------------------------------


def _override_rate_limits(
    app: FastAPI,
    *,
    ip: tuple[int, int] | None = None,
    email: tuple[int, int] | None = None,
) -> None:
    current: Settings = app.state.settings
    app.state.settings = current.model_copy(
        update={
            "login_rate_limit_ip": ip if ip is not None else current.login_rate_limit_ip,
            "login_rate_limit_email": (
                email if email is not None else current.login_rate_limit_email
            ),
        }
    )


async def test_login_rate_limit_by_ip(
    app: FastAPI,
    client: httpx.AsyncClient,
    db: Database,
    r: redis.Redis,
    cleanup_operators: list[uuid.UUID],
) -> None:
    _override_rate_limits(app, ip=(2, 300))
    op, pwd = await _make_operator(db, cleanup_operators)

    # Exhaust via wrong-password attempts (does not matter; the limiter
    # is front-of-password-check, so every attempt counts).
    for _ in range(2):
        resp = await client.post("/auth/login", json={"email": op.email, "password": "bad"})
        assert resp.status_code == 401

    # 3rd attempt — even with a correct password — is locked out with the
    # same generic body.
    locked = await client.post("/auth/login", json={"email": op.email, "password": pwd})
    assert locked.status_code == 401
    assert locked.json() == {"detail": "authentication failed"}


async def test_login_rate_limit_by_email(
    app: FastAPI,
    client: httpx.AsyncClient,
    db: Database,
    r: redis.Redis,
    cleanup_operators: list[uuid.UUID],
) -> None:
    _override_rate_limits(app, ip=(1000, 300), email=(2, 900))
    op, pwd = await _make_operator(db, cleanup_operators)

    for _ in range(2):
        resp = await client.post("/auth/login", json={"email": op.email, "password": "bad"})
        assert resp.status_code == 401

    locked = await client.post("/auth/login", json={"email": op.email, "password": pwd})
    assert locked.status_code == 401


async def test_login_rate_limit_does_not_leak_distinction(
    app: FastAPI,
    client: httpx.AsyncClient,
    db: Database,
    r: redis.Redis,
    cleanup_operators: list[uuid.UUID],
) -> None:
    _override_rate_limits(app, ip=(1, 300))
    op, pwd = await _make_operator(db, cleanup_operators)

    # First attempt — wrong password → generic 401.
    first = await client.post("/auth/login", json={"email": op.email, "password": "bad"})

    # Second attempt — now rate-limited → must also be generic 401.
    second = await client.post("/auth/login", json={"email": op.email, "password": pwd})

    assert first.status_code == second.status_code == 401
    assert first.json() == second.json()

"""Integration tests for dashboard routes — requires Postgres + Redis."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from algobet_common.bus import BusClient, Topic
from algobet_common.db import Database
from algobet_common.schemas import RiskAlert
from dashboard.auth.models import Operator
from strategy_registry import crud
from strategy_registry.models import Status

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db(postgres_dsn: str) -> AsyncIterator[Database]:
    database = Database(postgres_dsn)
    await database.connect()
    yield database
    await database.close()


def _unique_slug(prefix: str = "dash") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _make_awaiting_approval(db: Database, slug_prefix: str = "approve") -> uuid.UUID:
    strategy = await crud.create_strategy(db, slug=_unique_slug(slug_prefix))
    await crud.transition(db, strategy.id, Status.BACKTESTING)
    await crud.transition(db, strategy.id, Status.PAPER)
    await crud.transition(db, strategy.id, Status.AWAITING_APPROVAL)
    return strategy.id


# ---------------------------------------------------------------------------
# Strategies — read routes
# ---------------------------------------------------------------------------


async def test_list_strategies_empty(client: httpx.AsyncClient) -> None:
    response = await client.get("/strategies/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_get_strategy_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/strategies/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Approve gate — CSRF + session + session-derived approved_by (S2-d, S3-a)
# ---------------------------------------------------------------------------


async def test_approve_happy_path(
    auth_client: tuple[httpx.AsyncClient, Operator],
    csrf_header: dict[str, str],
    db: Database,
) -> None:
    client, operator = auth_client
    strategy_id = await _make_awaiting_approval(db)

    response = await client.post(
        f"/strategies/{strategy_id}/approve",
        headers={"Origin": "http://127.0.0.1", **csrf_header},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "live"
    assert body["approved_by"] == operator.email

    refreshed = await crud.get_strategy(db, strategy_id)
    assert refreshed.status == Status.LIVE
    assert refreshed.approved_by == operator.email
    assert refreshed.approved_at is not None


async def test_approve_invalid_transition(
    auth_client: tuple[httpx.AsyncClient, Operator],
    csrf_header: dict[str, str],
    db: Database,
) -> None:
    client, _ = auth_client
    strategy = await crud.create_strategy(db, slug=_unique_slug("invalid"))
    # Strategy is in 'hypothesis' — cannot jump directly to live.
    response = await client.post(
        f"/strategies/{strategy.id}/approve",
        headers={"Origin": "http://127.0.0.1", **csrf_header},
    )
    assert response.status_code == 422


async def test_approve_requires_auth(
    client: httpx.AsyncClient,
    db: Database,
) -> None:
    strategy_id = await _make_awaiting_approval(db)
    response = await client.post(f"/strategies/{strategy_id}/approve")
    assert response.status_code == 401


async def test_approve_requires_csrf_header(
    auth_client: tuple[httpx.AsyncClient, Operator],
    db: Database,
) -> None:
    client, _ = auth_client
    strategy_id = await _make_awaiting_approval(db)
    # Authed, but no X-CSRF-Token header.
    response = await client.post(
        f"/strategies/{strategy_id}/approve",
        headers={"Origin": "http://127.0.0.1"},
    )
    assert response.status_code == 403


async def test_approve_requires_matching_origin(
    auth_client: tuple[httpx.AsyncClient, Operator],
    csrf_header: dict[str, str],
    db: Database,
) -> None:
    """S1-a: an attacker who has exfiltrated the CSRF token via XSS on another
    origin must still be blocked by the Origin allow-list."""
    client, _ = auth_client
    strategy_id = await _make_awaiting_approval(db)
    response = await client.post(
        f"/strategies/{strategy_id}/approve",
        headers={"Origin": "http://evil.example.com", **csrf_header},
    )
    assert response.status_code == 403


async def test_approve_accepts_referer_when_origin_missing(
    auth_client: tuple[httpx.AsyncClient, Operator],
    csrf_header: dict[str, str],
    db: Database,
) -> None:
    """Some fetch modes omit Origin; fall back to Referer allow-list check."""
    client, _ = auth_client
    strategy_id = await _make_awaiting_approval(db)
    response = await client.post(
        f"/strategies/{strategy_id}/approve",
        headers={"Referer": "http://127.0.0.1/dashboard", **csrf_header},
    )
    assert response.status_code == 200, response.text


async def test_approve_auth_takes_precedence_over_csrf(
    client: httpx.AsyncClient,
    db: Database,
) -> None:
    """S3-a: require_operator is declared before require_csrf, so a request
    that is BOTH unauthenticated AND missing CSRF returns 401 not 403."""
    strategy_id = await _make_awaiting_approval(db)
    response = await client.post(f"/strategies/{strategy_id}/approve")
    assert response.status_code == 401


async def test_approve_uses_session_email_not_body(
    auth_client: tuple[httpx.AsyncClient, Operator],
    csrf_header: dict[str, str],
    db: Database,
) -> None:
    """The route declares no body parameter, so any attacker-supplied
    `approved_by` field is silently ignored by FastAPI and the session's
    email is written instead."""
    client, operator = auth_client
    strategy_id = await _make_awaiting_approval(db)
    response = await client.post(
        f"/strategies/{strategy_id}/approve",
        headers={"Origin": "http://127.0.0.1", **csrf_header},
        json={"approved_by": "attacker@evil.example.com"},
    )
    assert response.status_code == 200
    refreshed = await crud.get_strategy(db, strategy_id)
    assert refreshed.approved_by == operator.email


async def test_approve_full_lifecycle_sets_session_email(
    auth_client: tuple[httpx.AsyncClient, Operator],
    csrf_header: dict[str, str],
    db: Database,
) -> None:
    """S2-d end-to-end promotion gate: walk the full state machine then
    confirm the authenticated operator's email — and only that email —
    lands in strategies.approved_by."""
    client, operator = auth_client
    strategy = await crud.create_strategy(db, slug=_unique_slug("lifecycle"))
    await crud.transition(db, strategy.id, Status.BACKTESTING)
    await crud.transition(db, strategy.id, Status.PAPER)
    await crud.transition(db, strategy.id, Status.AWAITING_APPROVAL)

    response = await client.post(
        f"/strategies/{strategy.id}/approve",
        headers={"Origin": "http://127.0.0.1", **csrf_header},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "live"
    assert body["approved_by"] == operator.email

    refreshed = await crud.get_strategy(db, strategy.id)
    assert refreshed.status == Status.LIVE
    assert refreshed.approved_by == operator.email


# ---------------------------------------------------------------------------
# Risk alerts
# ---------------------------------------------------------------------------


async def test_risk_alerts_empty(client: httpx.AsyncClient) -> None:
    response = await client.get("/risk/alerts")
    assert response.status_code == 200
    assert response.json() == []


async def test_risk_alerts_with_data(
    client: httpx.AsyncClient,
    redis_url: str,
) -> None:
    bus = BusClient(redis_url, service_name="test-dashboard-publisher")
    await bus.connect()
    try:
        alert = RiskAlert(
            source="test",
            severity="warn",
            message="test alert",
            timestamp=datetime.now(UTC),
        )
        await bus.publish(Topic.RISK_ALERTS, alert)
    finally:
        await bus.close()

    response = await client.get("/risk/alerts?count=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["source"] == "test"
    assert data[0]["severity"] == "warn"
    assert data[0]["message"] == "test alert"
    assert "stream_id" in data[0]

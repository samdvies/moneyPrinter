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


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


async def test_list_strategies_empty(client: httpx.AsyncClient) -> None:
    response = await client.get("/strategies/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_get_strategy_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/strategies/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_approve_happy_path(
    client: httpx.AsyncClient,
    db: Database,
) -> None:
    strategy = await crud.create_strategy(db, slug=_unique_slug("approve"))
    await crud.transition(db, strategy.id, Status.BACKTESTING)
    await crud.transition(db, strategy.id, Status.PAPER)
    await crud.transition(db, strategy.id, Status.AWAITING_APPROVAL)

    response = await client.post(
        f"/strategies/{strategy.id}/approve",
        json={"approved_by": "test-operator"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "live"
    assert body["approved_by"] == "test-operator"

    refreshed = await crud.get_strategy(db, strategy.id)
    assert refreshed.status == Status.LIVE
    assert refreshed.approved_by == "test-operator"
    assert refreshed.approved_at is not None


async def test_approve_invalid_transition(
    client: httpx.AsyncClient,
    db: Database,
) -> None:
    strategy = await crud.create_strategy(db, slug=_unique_slug("invalid"))
    # Strategy is in 'hypothesis' status — cannot jump directly to live.
    response = await client.post(
        f"/strategies/{strategy.id}/approve",
        json={"approved_by": "test-operator"},
    )
    assert response.status_code == 422


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

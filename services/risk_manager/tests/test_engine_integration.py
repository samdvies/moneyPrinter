"""Integration tests for the risk_manager engine.

Requires Redis and Postgres service containers.
Tagged with pytest.mark.integration — skipped automatically when infra is absent.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import TypeVar
from urllib.parse import urlparse

import pytest
from algobet_common.bus import BusClient, Topic
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import OrderSide, OrderSignal, RiskAlert, Venue
from pydantic import BaseModel
from risk_manager.engine import run
from strategy_registry import crud
from strategy_registry.models import Mode, Status

pytestmark = pytest.mark.integration

_ENGINE_TIMEOUT = 5.0
TMessage = TypeVar("TMessage", bound=BaseModel)


def _make_settings(redis_url: str, postgres_dsn: str, **overrides: object) -> Settings:
    redis_parsed = urlparse(redis_url)
    pg_parsed = urlparse(postgres_dsn)

    redis_host = redis_parsed.hostname or "127.0.0.1"
    redis_port = redis_parsed.port or 6379
    redis_db = int(redis_parsed.path.lstrip("/") or "15")

    pg_host = pg_parsed.hostname or "127.0.0.1"
    pg_port = pg_parsed.port or 5432
    pg_db = pg_parsed.path.lstrip("/") or "algobet"
    pg_user = pg_parsed.username or "algobet"
    pg_password = pg_parsed.password or "devpassword"

    return Settings(
        service_name="risk-manager-test",
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=redis_db,
        postgres_host=pg_host,
        postgres_port=pg_port,
        postgres_db=pg_db,
        postgres_user=pg_user,
        postgres_password=pg_password,
        **overrides,  # type: ignore[arg-type]
    )


@pytest.fixture
async def bus(redis_url: str, _flush_redis: None, require_redis: None) -> AsyncIterator[BusClient]:
    """Publisher / reader bus — distinct service name so it reads its own consumer group."""
    client = BusClient(redis_url, service_name="risk-manager-test")
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
async def engine_bus(redis_url: str) -> AsyncIterator[BusClient]:
    """BusClient for the engine — uses the canonical 'risk-manager' consumer group."""
    client = BusClient(redis_url, service_name="risk-manager")
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
async def alert_bus(redis_url: str) -> AsyncIterator[BusClient]:
    """Dedicated reader for RISK_ALERTS (separate consumer group)."""
    client = BusClient(redis_url, service_name="risk-manager-alert-reader")
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
async def approved_bus(redis_url: str) -> AsyncIterator[BusClient]:
    """Dedicated reader for ORDER_SIGNALS_APPROVED (separate consumer group)."""
    client = BusClient(redis_url, service_name="risk-manager-approved-reader")
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
async def db(postgres_dsn: str, require_postgres: None) -> AsyncIterator[Database]:
    database = Database(postgres_dsn)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def live_strategy(db: Database) -> AsyncIterator[uuid.UUID]:
    """Create a strategy promoted all the way to 'live', plus a live strategy_run."""
    strategy = await crud.create_strategy(db, slug=f"rm-test-{uuid.uuid4().hex[:8]}")
    sid = strategy.id
    await crud.transition(db, sid, Status.BACKTESTING)
    await crud.transition(db, sid, Status.PAPER)
    await crud.transition(db, sid, Status.AWAITING_APPROVAL)
    await crud.transition(db, sid, Status.LIVE, approved_by="test-automation")
    await crud.start_run(db, sid, Mode.LIVE)
    yield sid
    async with db.acquire() as conn:
        await conn.execute("DELETE FROM strategy_runs WHERE strategy_id = $1", sid)
        await conn.execute("DELETE FROM strategies WHERE id = $1", sid)


async def _run_engine_bounded(
    engine_bus: BusClient,
    db: Database,
    settings: Settings,
    timeout: float = _ENGINE_TIMEOUT,
) -> None:
    """Drive the engine for up to `timeout` seconds then cancel."""
    with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
        await asyncio.wait_for(run(bus=engine_bus, db=db, settings=settings), timeout=timeout)


async def _collect(
    reader: BusClient,
    topic: Topic,
    model: type[TMessage],
    *,
    deadline: float,
    want: int = 1,
) -> list[TMessage]:
    results: list[TMessage] = []
    loop = asyncio.get_running_loop()
    while loop.time() < deadline and len(results) < want:
        async for msg in reader.consume(topic, model, count=5, block_ms=500):
            results.append(msg)
    return results


async def test_approve_happy_path(
    bus: BusClient,
    engine_bus: BusClient,
    approved_bus: BusClient,
    alert_bus: BusClient,
    db: Database,
    redis_url: str,
    postgres_dsn: str,
    live_strategy: uuid.UUID,
) -> None:
    """A valid live signal should flow to order.signals.approved with no alerts."""
    settings = _make_settings(redis_url, postgres_dsn, risk_kill_switch=False)
    signal = OrderSignal(
        strategy_id=str(live_strategy),
        mode="live",
        venue=Venue.BETFAIR,
        market_id="1.23",
        side=OrderSide.BACK,
        stake=Decimal("10"),
        price=Decimal("2.0"),
    )
    await bus.publish(Topic.ORDER_SIGNALS, signal)

    engine_task = asyncio.create_task(
        _run_engine_bounded(engine_bus, db, settings, timeout=_ENGINE_TIMEOUT)
    )

    loop = asyncio.get_event_loop()
    deadline = loop.time() + _ENGINE_TIMEOUT
    approved = await _collect(
        approved_bus, Topic.ORDER_SIGNALS_APPROVED, OrderSignal, deadline=deadline
    )

    engine_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await engine_task

    assert approved, "expected signal on order.signals.approved"
    assert approved[0].strategy_id == str(live_strategy)

    alerts = await _collect(alert_bus, Topic.RISK_ALERTS, RiskAlert, deadline=loop.time() + 0.5)
    assert not alerts, f"expected no alerts, got: {alerts}"


async def test_kill_switch_blocks_live_signal(
    bus: BusClient,
    engine_bus: BusClient,
    approved_bus: BusClient,
    alert_bus: BusClient,
    db: Database,
    redis_url: str,
    postgres_dsn: str,
    live_strategy: uuid.UUID,
) -> None:
    """A live signal with kill-switch active should produce a critical alert; nothing approved."""
    settings = _make_settings(redis_url, postgres_dsn, risk_kill_switch=True)
    signal = OrderSignal(
        strategy_id=str(live_strategy),
        mode="live",
        venue=Venue.BETFAIR,
        market_id="1.23",
        side=OrderSide.BACK,
        stake=Decimal("10"),
        price=Decimal("2.0"),
    )
    await bus.publish(Topic.ORDER_SIGNALS, signal)

    engine_task = asyncio.create_task(
        _run_engine_bounded(engine_bus, db, settings, timeout=_ENGINE_TIMEOUT)
    )

    loop = asyncio.get_event_loop()
    deadline = loop.time() + _ENGINE_TIMEOUT
    alerts = await _collect(alert_bus, Topic.RISK_ALERTS, RiskAlert, deadline=deadline)

    engine_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await engine_task

    assert alerts, "expected a critical RiskAlert on risk.alerts"
    assert alerts[0].severity == "critical"
    assert "kill-switch" in alerts[0].message.lower()

    approved = await _collect(
        approved_bus, Topic.ORDER_SIGNALS_APPROVED, OrderSignal, deadline=loop.time() + 0.5
    )
    assert not approved, "kill-switch must prevent approval"

"""End-to-end integration tests for the simulator engine.

Requires Redis and Postgres (TimescaleDB) service containers.
Tagged with pytest.mark.integration.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from algobet_common.bus import BusClient, Topic
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import (
    ExecutionResult,
    MarketData,
    OrderSide,
    OrderSignal,
    RiskAlert,
    Venue,
)
from simulator.engine import run

pytestmark = pytest.mark.integration

_ENGINE_TIMEOUT = 5.0  # seconds to wait for engine processing


@pytest.fixture
def settings(redis_url: str, postgres_dsn: str) -> Settings:
    return Settings(
        service_name="simulator-test",
        redis_host=redis_url.split("://")[1].split(":")[0],
        redis_port=int(redis_url.split(":")[-1].split("/")[0]),
        redis_db=int(redis_url.split("/")[-1]),
        postgres_host=postgres_dsn.split("@")[1].split(":")[0],
        postgres_port=int(postgres_dsn.split(":")[-1].split("/")[0]),
        postgres_db=postgres_dsn.split("/")[-1],
        postgres_user=postgres_dsn.split("://")[1].split(":")[0],
        postgres_password=postgres_dsn.split(":")[2].split("@")[0],
    )


@pytest.fixture
async def bus(redis_url: str, _flush_redis: None, require_redis: None) -> AsyncIterator[BusClient]:
    client = BusClient(redis_url, service_name="simulator-test")
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
async def engine_bus(redis_url: str) -> AsyncIterator[BusClient]:
    """Separate BusClient for the engine (different consumer group)."""
    client = BusClient(redis_url, service_name="simulator")
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
async def result_bus(redis_url: str) -> AsyncIterator[BusClient]:
    """BusClient for reading results (unique consumer group)."""
    client = BusClient(redis_url, service_name="simulator-result-reader")
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
async def strategy_and_run(db: Database) -> AsyncIterator[tuple[str, str]]:
    """Insert a test strategy + run and clean up after the test."""
    strategy_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO strategies (id, slug, status) VALUES ($1, $2, 'paper')",
            uuid.UUID(strategy_id),
            f"e2e-test-{strategy_id[:8]}",
        )
        await conn.execute(
            "INSERT INTO strategy_runs (id, strategy_id, mode) VALUES ($1, $2, 'paper')",
            uuid.UUID(run_id),
            uuid.UUID(strategy_id),
        )
    yield strategy_id, run_id
    async with db.acquire() as conn:
        await conn.execute("DELETE FROM orders WHERE strategy_id = $1", uuid.UUID(strategy_id))
        await conn.execute("DELETE FROM strategy_runs WHERE id = $1", uuid.UUID(run_id))
        await conn.execute("DELETE FROM strategies WHERE id = $1", uuid.UUID(strategy_id))


async def _run_engine_with_timeout(
    engine_bus: BusClient,
    db: Database,
    settings: Settings,
    run_id: str | None,
    stop: asyncio.Event,
    timeout: float = _ENGINE_TIMEOUT,
) -> None:
    """Run the engine until stop is set, with a hard timeout."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(
            run(bus=engine_bus, db=db, settings=settings, run_id=run_id, stop=stop),
            timeout=timeout,
        )


async def test_paper_signal_roundtrip(
    bus: BusClient,
    engine_bus: BusClient,
    result_bus: BusClient,
    db: Database,
    settings: Settings,
    strategy_and_run: tuple[str, str],
) -> None:
    """A paper OrderSignal that crosses produces an ExecutionResult and an orders row."""
    strategy_id, _run_id = strategy_and_run
    stop = asyncio.Event()

    tick = MarketData(
        venue=Venue.BETFAIR,
        market_id="e2e.001",
        timestamp=datetime.now(UTC),
        bids=[(Decimal("2.40"), Decimal("100.0"))],
        asks=[(Decimal("2.50"), Decimal("50.0"))],
    )
    signal = OrderSignal(
        strategy_id=strategy_id,
        mode="paper",
        venue=Venue.BETFAIR,
        market_id="e2e.001",
        side=OrderSide.BACK,
        stake=Decimal("10.00"),
        price=Decimal("2.60"),
    )

    # Publish the tick before starting the engine so the book is warm.
    await bus.publish(Topic.MARKET_DATA, tick)

    engine_task = asyncio.create_task(
        _run_engine_with_timeout(engine_bus, db, settings, None, stop, timeout=_ENGINE_TIMEOUT)
    )

    # Wait briefly for the engine to consume the tick into the book.
    await asyncio.sleep(0.5)
    await bus.publish(Topic.ORDER_SIGNALS, signal)

    results: list[ExecutionResult] = []
    deadline = asyncio.get_event_loop().time() + _ENGINE_TIMEOUT
    while asyncio.get_event_loop().time() < deadline and not results:
        async for r in result_bus.consume(
            Topic.EXECUTION_RESULTS, ExecutionResult, count=5, block_ms=500
        ):
            results.append(r)

    stop.set()
    await engine_task

    assert results, "expected at least one ExecutionResult on the bus"
    result = results[0]
    assert result.status == "filled"
    assert result.filled_stake == Decimal("10.00")
    assert result.filled_price == Decimal("2.50")
    assert result.mode == "paper"
    assert result.strategy_id == strategy_id

    async with db.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", uuid.UUID(result.order_id))
    assert row is not None
    assert row["status"] == "filled"
    assert row["venue"] == "betfair"


async def test_live_signal_rejected_with_risk_alert(
    bus: BusClient,
    engine_bus: BusClient,
    result_bus: BusClient,
    db: Database,
    settings: Settings,
    strategy_and_run: tuple[str, str],
) -> None:
    """A live-mode OrderSignal must never produce an ExecutionResult.

    The engine must emit a critical RiskAlert instead.
    """
    strategy_id, _run_id = strategy_and_run
    stop = asyncio.Event()

    alert_bus = BusClient(
        engine_bus._url,
        service_name="simulator-alert-reader",
    )
    await alert_bus.connect()

    signal = OrderSignal(
        strategy_id=strategy_id,
        mode="live",
        venue=Venue.BETFAIR,
        market_id="e2e.002",
        side=OrderSide.BACK,
        stake=Decimal("10.00"),
        price=Decimal("2.60"),
    )
    await bus.publish(Topic.ORDER_SIGNALS, signal)

    engine_task = asyncio.create_task(
        _run_engine_with_timeout(engine_bus, db, settings, None, stop, timeout=_ENGINE_TIMEOUT)
    )

    alerts: list[RiskAlert] = []
    execution_results: list[ExecutionResult] = []
    deadline = asyncio.get_event_loop().time() + _ENGINE_TIMEOUT
    while asyncio.get_event_loop().time() < deadline and not alerts:
        async for a in alert_bus.consume(Topic.RISK_ALERTS, RiskAlert, count=5, block_ms=500):
            alerts.append(a)
        async for r in result_bus.consume(
            Topic.EXECUTION_RESULTS, ExecutionResult, count=5, block_ms=100
        ):
            execution_results.append(r)

    stop.set()
    await engine_task
    await alert_bus.close()

    assert alerts, "expected a RiskAlert for live-mode signal"
    alert = alerts[0]
    assert alert.severity == "critical"
    assert "live-mode" in alert.message.lower() or "live" in alert.message.lower()
    assert not execution_results, "live-mode signal must NOT produce an ExecutionResult"


async def test_signal_with_invalid_strategy_uuid_emits_warn_alert(
    bus: BusClient,
    engine_bus: BusClient,
    db: Database,
    settings: Settings,
) -> None:
    """Malformed strategy UUIDs should not crash the engine loop."""
    stop = asyncio.Event()
    alert_bus = BusClient(engine_bus._url, service_name="simulator-alert-reader-uuid")
    await alert_bus.connect()

    signal = OrderSignal(
        strategy_id="not-a-uuid",
        mode="paper",
        venue=Venue.BETFAIR,
        market_id="e2e.003",
        side=OrderSide.BACK,
        stake=Decimal("10.00"),
        price=Decimal("2.60"),
    )
    await bus.publish(Topic.ORDER_SIGNALS, signal)

    engine_task = asyncio.create_task(
        _run_engine_with_timeout(
            engine_bus,
            db,
            settings,
            run_id=None,
            stop=stop,
            timeout=_ENGINE_TIMEOUT,
        )
    )

    alerts: list[RiskAlert] = []
    deadline = asyncio.get_event_loop().time() + _ENGINE_TIMEOUT
    while asyncio.get_event_loop().time() < deadline and not alerts:
        async for a in alert_bus.consume(Topic.RISK_ALERTS, RiskAlert, count=5, block_ms=500):
            alerts.append(a)

    stop.set()
    await engine_task
    await alert_bus.close()

    assert alerts, "expected warn RiskAlert for malformed strategy_id"
    assert alerts[0].severity == "warn"
    assert "not a valid uuid" in alerts[0].message.lower()

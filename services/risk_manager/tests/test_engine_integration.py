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
        await conn.execute("DELETE FROM orders WHERE strategy_id = $1", sid)
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


# ---------------------------------------------------------------------------
# Helpers for Task 5 cumulative-exposure tests
# ---------------------------------------------------------------------------


async def _insert_order(
    db: Database,
    strategy_id: uuid.UUID,
    *,
    venue: str,
    market_id: str,
    selection_id: str | None,
    side: str,
    stake: Decimal,
    price: Decimal,
    status: str = "placed",
    mode: str = "live",
) -> None:
    """Seed an order row directly into the DB, bypassing the simulator.

    Looks up the latest strategy_run for the given strategy_id and uses that
    as the run_id foreign-key value.
    """
    async with db.acquire() as conn:
        run_id = await conn.fetchval(
            "SELECT id FROM strategy_runs WHERE strategy_id = $1 ORDER BY started_at DESC LIMIT 1",
            strategy_id,
        )
        await conn.execute(
            """
            INSERT INTO orders (strategy_id, run_id, mode, venue, market_id, side,
                                stake, price, status, selection_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            strategy_id,
            run_id,
            mode,
            venue,
            market_id,
            side,
            stake,
            price,
            status,
            selection_id,
        )


# ---------------------------------------------------------------------------
# Task 5 — Test 1: cumulative exposure rejects second signal
# ---------------------------------------------------------------------------


async def test_cumulative_exposure_rejects_second_signal(
    bus: BusClient,
    engine_bus: BusClient,
    approved_bus: BusClient,
    alert_bus: BusClient,
    db: Database,
    redis_url: str,
    postgres_dsn: str,
    live_strategy: uuid.UUID,
) -> None:
    """Cumulative back-stake enforcement rejects a signal that would breach max_exposure_gbp.

    Arithmetic sanity (max_exposure_gbp = 1000 by DB default):
      Pre-existing order: back stake=700 @ 2.0, market='1.99', sel='A'
        → strategy_total = 700, market_liability = 700.

      Signal A: back stake=250 @ 2.0, sel='A'
        → projected market_after = 950 (back_stake=950, back_winnings=950, loss=950)
        -> projected_total = 700 - 700 + 950 = 950 <= 1000  APPROVED

      After seeding Signal A's placed order:
        strategy_total = 950, market_liability = 950.

      Signal B: back stake=200 @ 2.0, sel='A'
        → projected market_after = 1150
        -> projected_total = 950 - 950 + 1150 = 1150 > 1000  REJECTED
    """
    settings = _make_settings(redis_url, postgres_dsn, risk_kill_switch=False)

    # Seed pre-existing placed order: back 700 @ 2.0, market 1.99, sel 'A'.
    await _insert_order(
        db,
        live_strategy,
        venue="betfair",
        market_id="1.99",
        selection_id="A",
        side="back",
        stake=Decimal("700"),
        price=Decimal("2.0"),
        status="placed",
        mode="live",
    )

    # Publish Signal A: back 250 @ 2.0.
    signal_a = OrderSignal(
        strategy_id=str(live_strategy),
        mode="live",
        venue=Venue.BETFAIR,
        market_id="1.99",
        side=OrderSide.BACK,
        stake=Decimal("250"),
        price=Decimal("2.0"),
        selection_id="A",
    )
    await bus.publish(Topic.ORDER_SIGNALS, signal_a)
    await _run_engine_bounded(engine_bus, db, settings, timeout=_ENGINE_TIMEOUT)

    # Seed the placed order for Signal A (simulating what the simulator would write).
    await _insert_order(
        db,
        live_strategy,
        venue="betfair",
        market_id="1.99",
        selection_id="A",
        side="back",
        stake=Decimal("250"),
        price=Decimal("2.0"),
        status="placed",
        mode="live",
    )

    # Publish Signal B: back 200 @ 2.0 — should breach the 1000 cap.
    signal_b = OrderSignal(
        strategy_id=str(live_strategy),
        mode="live",
        venue=Venue.BETFAIR,
        market_id="1.99",
        side=OrderSide.BACK,
        stake=Decimal("200"),
        price=Decimal("2.0"),
        selection_id="A",
    )
    await bus.publish(Topic.ORDER_SIGNALS, signal_b)
    await _run_engine_bounded(engine_bus, db, settings, timeout=_ENGINE_TIMEOUT)

    # Collect all approved messages across both engine runs (consumer group tracks position).
    loop = asyncio.get_event_loop()
    approved = await _collect(
        approved_bus,
        Topic.ORDER_SIGNALS_APPROVED,
        OrderSignal,
        deadline=loop.time() + 2.0,
        want=2,  # try to collect up to 2; we expect exactly 1
    )
    alerts = await _collect(
        alert_bus,
        Topic.RISK_ALERTS,
        RiskAlert,
        deadline=loop.time() + 2.0,
        want=1,
    )

    # Only Signal A should have been approved.
    assert (
        len(approved) == 1
    ), f"expected exactly 1 approved signal (Signal A), got {len(approved)}: {approved}"
    assert approved[0].stake == Decimal(
        "250"
    ), f"expected approved signal to have stake=250, got {approved[0].stake}"

    # Exactly one warn alert whose message mentions 'projected' and 'exceed'.
    assert (
        len(alerts) == 1
    ), f"expected exactly 1 risk alert for Signal B rejection, got {len(alerts)}: {alerts}"
    assert alerts[0].severity == "warn", f"expected warn severity, got {alerts[0].severity!r}"
    assert (
        "projected" in alerts[0].message
    ), f"expected 'projected' in alert message, got: {alerts[0].message!r}"
    assert (
        "exceed" in alerts[0].message
    ), f"expected 'exceed' in alert message, got: {alerts[0].message!r}"


# ---------------------------------------------------------------------------
# Task 5 — Test 2: burst race — advisory lock serialises checks but does NOT
#           fix the approved-but-unplaced window
# ---------------------------------------------------------------------------


async def test_burst_race_serialised_by_advisory_lock(
    bus: BusClient,
    engine_bus: BusClient,
    approved_bus: BusClient,
    db: Database,
    redis_url: str,
    postgres_dsn: str,
    live_strategy: uuid.UUID,
) -> None:
    """Documents the approved-but-unplaced race that the advisory lock does NOT close.

    Both signals are published before any order row is written for Signal A.
    When the engine processes them sequentially (advisory lock ensures this),
    Signal A's exposure check reads strategy_total=700.  Before Signal A's
    approved order is written to the DB by the simulator, Signal B's check
    ALSO reads strategy_total=700.  Both project under-cap (950 and 900
    respectively) and are both approved.

    This is the DOCUMENTED CURRENT BEHAVIOUR — a known open debt.  The full
    fix (risk-manager-writes-orders or a liability_reservations table) is
    tracked in wiki/20-Risk/open-debts.md.

    # TODO: when the order_id / reservations remediation lands, this test
    # MUST be rewritten to assert exactly ONE approved signal (Signal B at
    # stake=200 would then be rejected because Signal A's reservation would
    # already be accounted for).  The test should flip from `assert len == 2`
    # to `assert len == 1`.
    """
    # See wiki/20-Risk/open-debts.md — "Approved-but-unplaced race" debt item.
    settings = _make_settings(redis_url, postgres_dsn, risk_kill_switch=False)

    # Seed pre-existing back 700 @ 2.0, market 1.99, sel 'A'.
    await _insert_order(
        db,
        live_strategy,
        venue="betfair",
        market_id="1.99",
        selection_id="A",
        side="back",
        stake=Decimal("700"),
        price=Decimal("2.0"),
        status="placed",
        mode="live",
    )

    # Publish Signal A and Signal B back-to-back with NO order seeded between them.
    # Both will read strategy_total_liability_before = 700 (stale state).
    signal_a = OrderSignal(
        strategy_id=str(live_strategy),
        mode="live",
        venue=Venue.BETFAIR,
        market_id="1.99",
        side=OrderSide.BACK,
        stake=Decimal("250"),
        price=Decimal("2.0"),
        selection_id="A",
    )
    signal_b = OrderSignal(
        strategy_id=str(live_strategy),
        mode="live",
        venue=Venue.BETFAIR,
        market_id="1.99",
        side=OrderSide.BACK,
        stake=Decimal("200"),
        price=Decimal("2.0"),
        selection_id="A",
    )
    await bus.publish(Topic.ORDER_SIGNALS, signal_a)
    await bus.publish(Topic.ORDER_SIGNALS, signal_b)

    # Run engine long enough to process both signals.
    await _run_engine_bounded(engine_bus, db, settings, timeout=_ENGINE_TIMEOUT)

    # Collect up to 2 approved messages.
    loop = asyncio.get_event_loop()
    approved = await _collect(
        approved_bus,
        Topic.ORDER_SIGNALS_APPROVED,
        OrderSignal,
        deadline=loop.time() + 3.0,
        want=2,
    )

    # DOCUMENTED CURRENT BEHAVIOUR: both signals are approved because Signal B
    # reads stale DB state (Signal A's order has not been written yet).
    # When the approved-but-unplaced remediation lands, change `== 2` to `== 1`.
    assert (
        len(approved) == 2
    ), f"expected both signals approved (race not yet fixed), got {len(approved)}: {approved}"

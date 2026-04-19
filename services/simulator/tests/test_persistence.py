"""Integration tests for persistence helpers.

Requires Postgres (TimescaleDB) to be available.
Tagged with pytest.mark.integration.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from algobet_common.db import Database
from algobet_common.schemas import ExecutionResult, OrderSide, OrderSignal, Venue
from simulator.persistence import record_fill, record_order

pytestmark = pytest.mark.integration


@pytest.fixture
async def db(postgres_dsn: str, require_postgres: None) -> AsyncIterator[Database]:
    database = Database(postgres_dsn)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def strategy_and_run(db: Database) -> AsyncIterator[tuple[str, str]]:
    """Insert a test strategy + run row; clean up on teardown."""
    strategy_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO strategies (id, slug, status)
            VALUES ($1, $2, 'paper')
            """,
            uuid.UUID(strategy_id),
            f"test-strat-{strategy_id[:8]}",
        )
        await conn.execute(
            """
            INSERT INTO strategy_runs (id, strategy_id, mode)
            VALUES ($1, $2, 'paper')
            """,
            uuid.UUID(run_id),
            uuid.UUID(strategy_id),
        )
    yield strategy_id, run_id
    async with db.acquire() as conn:
        await conn.execute("DELETE FROM orders WHERE strategy_id = $1", uuid.UUID(strategy_id))
        await conn.execute("DELETE FROM strategy_runs WHERE id = $1", uuid.UUID(run_id))
        await conn.execute("DELETE FROM strategies WHERE id = $1", uuid.UUID(strategy_id))


def _signal(strategy_id: str) -> OrderSignal:
    return OrderSignal(
        strategy_id=strategy_id,
        mode="paper",
        venue=Venue.BETFAIR,
        market_id="persist.001",
        side=OrderSide.BACK,
        stake=Decimal("10.00"),
        price=Decimal("2.50"),
    )


def _result(order_id: str, strategy_id: str) -> ExecutionResult:
    return ExecutionResult(
        order_id=order_id,
        strategy_id=strategy_id,
        mode="paper",
        status="filled",
        filled_stake=Decimal("10.00"),
        filled_price=Decimal("2.50"),
        timestamp=datetime.now(UTC),
    )


async def test_record_order_inserts_row(db: Database, strategy_and_run: tuple[str, str]) -> None:
    strategy_id, run_id = strategy_and_run
    order_id = str(uuid.uuid4())
    signal = _signal(strategy_id)

    alert = await record_order(signal, order_id, run_id, db)
    assert alert is None

    async with db.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", uuid.UUID(order_id))
    assert row is not None
    assert row["status"] == "placed"
    assert row["venue"] == "betfair"
    assert row["market_id"] == "persist.001"


async def test_record_fill_updates_row(db: Database, strategy_and_run: tuple[str, str]) -> None:
    strategy_id, run_id = strategy_and_run
    order_id = str(uuid.uuid4())
    signal = _signal(strategy_id)

    await record_order(signal, order_id, run_id, db)
    result = _result(order_id, strategy_id)
    await record_fill(result, run_id, db)

    async with db.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", uuid.UUID(order_id))
    assert row is not None
    assert row["status"] == "filled"
    assert row["filled_price"] is not None


async def test_record_order_missing_strategy_emits_alert(
    db: Database, require_postgres: None
) -> None:
    """If strategy_id doesn't exist, record_order returns a warn RiskAlert."""
    order_id = str(uuid.uuid4())
    bad_strategy_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    signal = _signal(bad_strategy_id)

    alert = await record_order(signal, order_id, run_id, db)
    assert alert is not None
    assert alert.severity == "warn"
    assert "strategy_id" in alert.message


async def test_record_order_missing_run_emits_alert(
    db: Database, strategy_and_run: tuple[str, str]
) -> None:
    """If run_id doesn't exist, record_order returns a warn RiskAlert."""
    strategy_id, _run_id = strategy_and_run
    order_id = str(uuid.uuid4())
    bad_run_id = str(uuid.uuid4())
    signal = _signal(strategy_id)

    alert = await record_order(signal, order_id, bad_run_id, db)
    assert alert is not None
    assert alert.severity == "warn"
    assert "run_id" in alert.message

"""Async engine: connects book, fills, bus, and persistence.

Two concurrent consumers:
  1. MARKET_DATA   → update in-memory Book
  2. ORDER_SIGNALS → filter mode=="paper", dispatch fills, publish results

Live-mode signals are rejected immediately and a critical RiskAlert is emitted.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from algobet_common.bus import BusClient, Topic
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import ExecutionResult, MarketData, OrderSignal, RiskAlert

from simulator.book import Book
from simulator.fills import match_order
from simulator.persistence import record_fill, record_order

logger = logging.getLogger(__name__)

_SERVICE = "simulator"


def _rest_result(signal: OrderSignal) -> ExecutionResult:
    """Produce a resting (unfilled) result for a signal with no book snapshot."""
    return ExecutionResult(
        order_id=str(uuid.uuid4()),
        strategy_id=signal.strategy_id,
        mode=signal.mode,
        status="placed",
        filled_stake=Decimal("0"),
        filled_price=None,
        timestamp=datetime.now(UTC),
    )


async def _consume_market_data(bus: BusClient, book: Book, stop: asyncio.Event) -> None:
    while not stop.is_set():
        async for tick in bus.consume(Topic.MARKET_DATA, MarketData, block_ms=1000):
            book.update(tick)
            logger.info(
                "[%s] book updated venue=%s market=%s ts=%s",
                _SERVICE,
                tick.venue,
                tick.market_id,
                tick.timestamp.isoformat(),
            )


async def _consume_order_signals(
    bus: BusClient,
    db: Database,
    book: Book,
    stop: asyncio.Event,
    run_id: str | None = None,
) -> None:
    while not stop.is_set():
        async for signal in bus.consume(Topic.ORDER_SIGNALS, OrderSignal, block_ms=1000):
            if signal.mode == "live":
                alert = RiskAlert(
                    source=_SERVICE,
                    severity="critical",
                    message=(
                        f"live-mode OrderSignal rejected by simulator: "
                        f"strategy_id={signal.strategy_id!r} "
                        f"venue={signal.venue} market={signal.market_id}"
                    ),
                    timestamp=datetime.now(UTC),
                )
                await bus.publish(Topic.RISK_ALERTS, alert)
                logger.error("[%s] REJECTED live-mode signal: %s", _SERVICE, alert.message)
                continue

            effective_run_id = run_id
            if effective_run_id is None:
                try:
                    strategy_uuid = uuid.UUID(signal.strategy_id)
                except ValueError:
                    alert = RiskAlert(
                        source=_SERVICE,
                        severity="warn",
                        message=(
                            "OrderSignal dropped: strategy_id is not a valid UUID "
                            f"({signal.strategy_id!r})"
                        ),
                        timestamp=datetime.now(UTC),
                    )
                    await bus.publish(Topic.RISK_ALERTS, alert)
                    logger.warning("[%s] %s", _SERVICE, alert.message)
                    continue

                async with db.acquire() as conn:
                    resolved = await conn.fetchval(
                        """
                        SELECT id
                        FROM strategy_runs
                        WHERE strategy_id = $1 AND mode = 'paper'
                        ORDER BY started_at DESC
                        LIMIT 1
                        """,
                        strategy_uuid,
                    )

                if resolved is None:
                    alert = RiskAlert(
                        source=_SERVICE,
                        severity="warn",
                        message=(
                            "OrderSignal dropped: no paper strategy_run found "
                            f"for strategy_id={signal.strategy_id!r}"
                        ),
                        timestamp=datetime.now(UTC),
                    )
                    await bus.publish(Topic.RISK_ALERTS, alert)
                    logger.warning("[%s] %s", _SERVICE, alert.message)
                    continue
                effective_run_id = str(resolved)

            snap = book.get(signal.venue, signal.market_id)
            if snap is None:
                logger.warning(
                    "[%s] no book snapshot for venue=%s market=%s; signal resting",
                    _SERVICE,
                    signal.venue,
                    signal.market_id,
                )

            result = match_order(signal, snap) if snap is not None else _rest_result(signal)

            record_alert = await record_order(signal, result.order_id, effective_run_id, db)
            if record_alert is not None:
                await bus.publish(Topic.RISK_ALERTS, record_alert)
                continue

            await record_fill(result, effective_run_id, db)
            await bus.publish(Topic.EXECUTION_RESULTS, result)
            logger.info(
                "[%s] filled order_id=%s status=%s filled_stake=%s filled_price=%s",
                _SERVICE,
                result.order_id,
                result.status,
                result.filled_stake,
                result.filled_price,
            )


async def run(
    bus: BusClient,
    db: Database,
    settings: Settings,
    run_id: str | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Run the simulator until `stop` is set (or forever if stop is None)."""
    _stop = stop or asyncio.Event()
    book = Book()
    logger.info("[%s] engine starting", _SERVICE)
    await asyncio.gather(
        _consume_market_data(bus, book, _stop),
        _consume_order_signals(bus, db, book, _stop, run_id=run_id),
    )
    logger.info("[%s] engine stopped", _SERVICE)

"""Persistence helpers for the simulator.

Inserts/updates rows in the `orders` table via `algobet_common.db.Database`.
No new migrations — the existing schema (0002_strategy_registry.sql) is reused.

If `strategy_id` or `run_id` are missing from the registry, the signal is
dropped and a `RiskAlert` with severity="warn" is returned rather than
inserting a dangling FK row.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import asyncpg
from algobet_common.db import Database
from algobet_common.schemas import ExecutionResult, OrderSignal, RiskAlert

logger = logging.getLogger(__name__)

_SERVICE = "simulator"


def _warn_alert(message: str) -> RiskAlert:
    alert = RiskAlert(
        source=_SERVICE,
        severity="warn",
        message=message,
        timestamp=datetime.now(UTC),
    )
    logger.warning("[%s] %s", _SERVICE, alert.message)
    return alert


async def record_order(
    signal: OrderSignal,
    order_id: str,
    run_id: str,
    db: Database,
) -> RiskAlert | None:
    """Insert an order row.

    Returns a RiskAlert if the strategy/run registry rows are missing,
    otherwise returns None on success.
    """
    try:
        strategy_uuid = uuid.UUID(signal.strategy_id)
    except ValueError:
        return _warn_alert(
            f"OrderSignal dropped: strategy_id is not a valid UUID ({signal.strategy_id!r})"
        )

    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        return _warn_alert(f"OrderSignal dropped: run_id is not a valid UUID ({run_id!r})")

    async with db.acquire() as conn:
        strategy_exists = await conn.fetchval(
            "SELECT 1 FROM strategies WHERE id = $1",
            strategy_uuid,
        )
        if not strategy_exists:
            return _warn_alert(
                f"OrderSignal dropped: strategy_id={signal.strategy_id!r} not found in registry"
            )

        run_exists = await conn.fetchval(
            "SELECT 1 FROM strategy_runs WHERE id = $1",
            run_uuid,
        )
        if not run_exists:
            return _warn_alert(f"OrderSignal dropped: run_id={run_id!r} not found in registry")

        try:
            await conn.execute(
                """
                INSERT INTO orders (
                    id, strategy_id, run_id, mode, venue, market_id,
                    side, stake, price, status, placed_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                uuid.UUID(order_id),
                strategy_uuid,
                run_uuid,
                signal.mode,
                signal.venue.value,
                signal.market_id,
                signal.side.value,
                float(signal.stake),
                float(signal.price),
                "placed",
                datetime.now(UTC),
            )
        except asyncpg.ForeignKeyViolationError as exc:
            return _warn_alert(f"OrderSignal dropped: FK violation — {exc}")

    return None


async def record_fill(result: ExecutionResult, run_id: str, db: Database) -> None:
    """Update an existing order row with fill data."""
    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE orders
            SET status       = $1,
                filled_price = $2,
                filled_at    = $3
            WHERE id = $4
            """,
            result.status,
            float(result.filled_price) if result.filled_price is not None else None,
            result.timestamp if result.status in ("filled", "partially_filled") else None,
            uuid.UUID(result.order_id),
        )

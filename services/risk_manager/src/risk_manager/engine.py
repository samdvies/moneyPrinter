"""Async engine: consumes order signals, applies rules, approves or rejects.

Approved signals are republished to Topic.ORDER_SIGNALS_APPROVED.
Rejected signals emit a RiskAlert on Topic.RISK_ALERTS.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from algobet_common.bus import BusClient, Topic
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import OrderSignal, RiskAlert
from strategy_registry import crud
from strategy_registry.errors import StrategyNotFoundError

from .rules import (
    RuleResult,
    check_exposure,
    check_kill_switch,
    check_registry_mode,
    check_venue_notional,
)

logger = logging.getLogger(__name__)

_SERVICE = "risk-manager"
_ALERT_SOURCE = "risk_manager"


async def _fetch_strategy_and_run(
    db: Database,
    signal: OrderSignal,
) -> tuple[str | None, str | None]:
    """Return (strategy_status, latest_run_mode) for the signal's strategy.

    Returns (None, None) when strategy_id is malformed or not found.
    """
    try:
        strategy_uuid = uuid.UUID(signal.strategy_id)
    except ValueError:
        logger.warning(
            "[%s] malformed strategy_id=%r in signal; treating as not found",
            _SERVICE,
            signal.strategy_id,
        )
        return None, None

    try:
        strategy = await crud.get_strategy(db, strategy_uuid)
    except StrategyNotFoundError:
        logger.warning(
            "[%s] strategy_id=%r not found in registry",
            _SERVICE,
            signal.strategy_id,
        )
        return None, None

    async with db.acquire() as conn:
        run_mode: str | None = await conn.fetchval(
            """
            SELECT mode
            FROM strategy_runs
            WHERE strategy_id = $1
            ORDER BY started_at DESC
            LIMIT 1
            """,
            strategy_uuid,
        )

    return strategy.status.value, run_mode


def _apply_rules(
    signal: OrderSignal,
    strategy_status: str | None,
    run_mode: str | None,
    settings: Settings,
) -> RuleResult:
    """Run all four rules in order; stop at first failure."""
    for result in (
        check_kill_switch(signal, settings),
        check_exposure(signal, settings),
        check_venue_notional(signal, settings),
        check_registry_mode(signal, strategy_status, run_mode),
    ):
        if not result.passed:
            return result
    return RuleResult.ok()


async def run(bus: BusClient, db: Database, settings: Settings) -> None:
    """Infinite consume loop — runs until cancelled."""
    logger.info("[%s] engine starting", _SERVICE)
    while True:
        async for signal in bus.consume(Topic.ORDER_SIGNALS, OrderSignal):
            strategy_status, run_mode = await _fetch_strategy_and_run(db, signal)
            result = _apply_rules(signal, strategy_status, run_mode, settings)

            if result.passed:
                await bus.publish(Topic.ORDER_SIGNALS_APPROVED, signal)
                logger.info(
                    "[%s] APPROVED strategy_id=%r venue=%s market=%s mode=%s",
                    _SERVICE,
                    signal.strategy_id,
                    signal.venue,
                    signal.market_id,
                    signal.mode,
                )
            else:
                severity = result.severity if result.severity is not None else "warn"
                alert = RiskAlert(
                    source=_ALERT_SOURCE,
                    severity=severity,
                    message=result.reason or "rule check failed",
                    timestamp=datetime.now(UTC),
                )
                await bus.publish(Topic.RISK_ALERTS, alert)
                if result.severity == "critical":
                    logger.error(
                        "[%s] REJECTED (critical) strategy_id=%r reason=%r",
                        _SERVICE,
                        signal.strategy_id,
                        result.reason,
                    )
                else:
                    logger.warning(
                        "[%s] REJECTED (warn) strategy_id=%r reason=%r",
                        _SERVICE,
                        signal.strategy_id,
                        result.reason,
                    )

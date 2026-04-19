"""Async engine: consumes order signals, applies rules, approves or rejects.

Approved signals are republished to Topic.ORDER_SIGNALS_APPROVED.
Rejected signals emit a RiskAlert on Topic.RISK_ALERTS.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

from algobet_common.bus import BusClient, Topic
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import OrderSignal, RiskAlert
from strategy_registry.models import LiabilityComponents

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

# Sentinel zero-components for paths that short-circuit before DB queries.
_ZERO_COMPONENTS = LiabilityComponents(
    back_stake=Decimal("0"),
    lay_stake=Decimal("0"),
    back_winnings=Decimal("0"),
    lay_liability=Decimal("0"),
)


@asynccontextmanager
async def _acquire_exposure_context(
    db: Database,
    signal: OrderSignal,
) -> AsyncIterator[tuple[str | None, str | None, Decimal, LiabilityComponents, Decimal]]:
    """Acquire a per-strategy Postgres advisory lock and fetch all exposure inputs.

    The advisory lock is a transaction-level lock (pg_advisory_xact_lock), which is
    held for the duration of the transaction.  The caller publishes the approval or
    alert *inside* this async-with block so the lock covers the downstream publish
    before releasing.

    Yields a 5-tuple:
        (strategy_status, run_mode, total_liability, market_components, max_exposure_gbp)

    When strategy_id is malformed or the strategy row is missing, yields
    (None, None, Decimal("0"), zero_components, settings_default) and the caller
    will reject via check_registry_mode.
    """
    try:
        strategy_uuid = uuid.UUID(signal.strategy_id)
    except ValueError:
        logger.warning(
            "[%s] malformed strategy_id=%r in signal; treating as not found",
            _SERVICE,
            signal.strategy_id,
        )
        # Yield defaults without a DB transaction — check_registry_mode will reject.
        yield (None, None, Decimal("0"), _ZERO_COMPONENTS, Decimal("1000"))
        return

    async with db.acquire() as conn, conn.transaction():
        # Serialise same-strategy checks across replicas.
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('risk:exposure:' || $1::text))",
            str(strategy_uuid),
        )

        # Fetch strategy row inline (Option A — same connection as the lock).
        strategy_row = await conn.fetchrow(
            "SELECT * FROM strategies WHERE id = $1",
            strategy_uuid,
        )
        if strategy_row is None:
            logger.warning(
                "[%s] strategy_id=%r not found in registry",
                _SERVICE,
                signal.strategy_id,
            )
            yield (None, None, Decimal("0"), _ZERO_COMPONENTS, Decimal("1000"))
            return

        strategy_status: str = strategy_row["status"]
        max_exposure_gbp: Decimal = Decimal(str(strategy_row["max_exposure_gbp"]))

        # Latest run mode for this strategy.
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

        # Total open liability across all markets for this strategy.
        liability_rows = await conn.fetch(
            """
            SELECT back_stake, lay_stake, back_winnings, lay_liability
            FROM open_order_liability
            WHERE strategy_id = $1
            """,
            strategy_uuid,
        )
        total_liability = Decimal("0")
        for row in liability_rows:
            comp = LiabilityComponents(
                back_stake=Decimal(str(row["back_stake"])),
                lay_stake=Decimal(str(row["lay_stake"])),
                back_winnings=Decimal(str(row["back_winnings"])),
                lay_liability=Decimal(str(row["lay_liability"])),
            )
            total_liability += comp.market_liability

        # Existing components for the signal's (venue, market, selection) group.
        market_row = await conn.fetchrow(
            """
            SELECT back_stake, lay_stake, back_winnings, lay_liability
            FROM open_order_liability
            WHERE strategy_id = $1
              AND venue = $2
              AND market_id = $3
              AND selection_id_key = COALESCE($4, '__none__')
            """,
            strategy_uuid,
            signal.venue.value,
            signal.market_id,
            signal.selection_id,
        )
        if market_row is None:
            market_components = _ZERO_COMPONENTS
        else:
            market_components = LiabilityComponents(
                back_stake=Decimal(str(market_row["back_stake"])),
                lay_stake=Decimal(str(market_row["lay_stake"])),
                back_winnings=Decimal(str(market_row["back_winnings"])),
                lay_liability=Decimal(str(market_row["lay_liability"])),
            )

        yield (strategy_status, run_mode, total_liability, market_components, max_exposure_gbp)


def _apply_rules(
    signal: OrderSignal,
    *,
    strategy_status: str | None,
    run_mode: str | None,
    total_liability: Decimal,
    market_components: LiabilityComponents,
    max_exposure_gbp: Decimal,
    settings: Settings,
) -> RuleResult:
    """Run all four rules in order; stop at first failure.

    Rule ordering: kill_switch → venue_notional → registry_mode → exposure.
    Rationale: kill-switch and venue-notional are stateless and cheap;
    registry-mode establishes strategy existence; exposure depends on the
    strategy row being present.
    """
    for result in (
        check_kill_switch(signal, settings),
        check_venue_notional(signal, settings),
        check_registry_mode(signal, strategy_status, run_mode),
        check_exposure(
            signal,
            strategy_total_liability_before=total_liability,
            market_components_before=market_components,
            max_exposure_gbp=max_exposure_gbp,
            per_signal_cap_gbp=settings.risk_max_signal_liability_gbp,
        ),
    ):
        if not result.passed:
            return result
    return RuleResult.ok()


async def run(bus: BusClient, db: Database, settings: Settings) -> None:
    """Infinite consume loop — runs until cancelled."""
    logger.info("[%s] engine starting", _SERVICE)
    while True:
        async for signal in bus.consume(Topic.ORDER_SIGNALS, OrderSignal):
            async with _acquire_exposure_context(db, signal) as (
                status,
                run_mode,
                total_liab,
                market_comp,
                max_exp_gbp,
            ):
                result = _apply_rules(
                    signal,
                    strategy_status=status,
                    run_mode=run_mode,
                    total_liability=total_liab,
                    market_components=market_comp,
                    max_exposure_gbp=max_exp_gbp,
                    settings=settings,
                )

                # Publish inside the with-block so the advisory lock covers the publish.
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

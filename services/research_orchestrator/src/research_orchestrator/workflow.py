"""Stub workflow functions for the research orchestrator.

These three functions implement the core research loop:
- hypothesize: generate a trading hypothesis (stub returns a fixed dict)
- run_backtest: evaluate a hypothesis (stub returns zeros)
- promote: advance a strategy through the lifecycle via the registry gate
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from algobet_common.bus import BusClient, Topic
from algobet_common.db import Database
from strategy_registry import crud
from strategy_registry.models import Status, Strategy

from .errors import OrchestratorError
from .schemas import ResearchEvent

logger = logging.getLogger(__name__)

# Transitions the orchestrator is explicitly forbidden from requesting.
# paper → awaiting-approval is a human decision via the dashboard.
# awaiting-approval → live requires dashboard approval with approved_by.
_FORBIDDEN_TRANSITIONS: frozenset[Status] = frozenset({Status.LIVE, Status.AWAITING_APPROVAL})


async def hypothesize() -> dict[str, Any]:
    """Return a fixed stub hypothesis. Real generation (Claude API) is Phase 5."""
    hypothesis: dict[str, Any] = {
        "name": "stub-hypothesis",
        "description": "placeholder",
        "venue": "betfair",
    }
    logger.info("hypothesize: returning stub hypothesis %s", hypothesis["name"])
    return hypothesis


async def run_backtest(hypothesis: dict[str, Any]) -> dict[str, Any]:
    """Run a stub backtest. Real backtesting logic is Phase 5."""
    logger.info("run_backtest: running stub backtest for hypothesis %s", hypothesis.get("name"))
    return {"sharpe": 0.0, "total_pnl_gbp": 0.0, "n_trades": 0, "status": "stub"}


async def promote(
    db: Database,
    bus: BusClient,
    strategy_id: uuid.UUID,
    to_status: Status,
) -> Strategy:
    """Advance a strategy to a new lifecycle status.

    Enforces the orchestrator's authority boundary: transitions to
    LIVE or AWAITING_APPROVAL are reserved for humans via the dashboard
    and will raise OrchestratorError before any DB call.

    Publishes a ResearchEvent to Topic.RESEARCH_EVENTS only after the
    transition succeeds, so consumers never see misleading events.
    """
    if to_status in _FORBIDDEN_TRANSITIONS:
        raise OrchestratorError(
            f"orchestrator may not request transition to {to_status}; "
            "use the dashboard approval route"
        )

    current = await crud.get_strategy(db, strategy_id)
    from_status = current.status

    updated = await crud.transition(db, strategy_id, to_status)

    event = ResearchEvent(
        event_type="strategy_transition",
        strategy_id=str(strategy_id),
        from_status=str(from_status),
        to_status=str(to_status),
        timestamp=datetime.now(UTC),
    )
    await bus.publish(Topic.RESEARCH_EVENTS, event)

    logger.info(
        "promote: strategy %s transitioned %s → %s",
        strategy_id,
        from_status,
        to_status,
    )
    return updated

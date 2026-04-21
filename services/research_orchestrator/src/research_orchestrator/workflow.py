"""Workflow functions for the research orchestrator.

These functions implement the core research loop:

- ``hypothesize`` — generate a trading hypothesis (stub for now; real
  Claude-API generation lands in a later phase).
- ``run_backtest`` — production path: a thin delegate onto
  ``backtest_engine.run_backtest`` so the orchestrator can keep calling
  ``workflow.run_backtest`` in its own namespace.
- ``promote`` — advance a strategy through the lifecycle via the registry
  gate.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from algobet_common.bus import BusClient, Topic
from algobet_common.db import Database
from backtest_engine.harness import BacktestResult
from backtest_engine.harness import run_backtest as _harness_run_backtest
from backtest_engine.strategy_protocol import StrategyModule, TickSource
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


async def run_backtest(
    strategy_id: uuid.UUID,
    strategy: StrategyModule,
    params: dict[str, Any],
    source: TickSource,
    time_range: tuple[datetime, datetime],
    db: Database,
) -> BacktestResult:
    """Production backtest path — thin delegate onto the real harness.

    The orchestrator keeps its own ``workflow.run_backtest`` name so callers
    (``runner.run_once``) don't need to import ``backtest_engine`` directly.
    All DB bookkeeping (``strategy_runs`` start_run / end_run) is handled
    inside the harness when ``db`` + ``strategy_id`` are supplied.
    """
    logger.info(
        "run_backtest: dispatching harness for strategy %s over [%s, %s]",
        strategy_id,
        time_range[0].isoformat(),
        time_range[1].isoformat(),
    )
    return await _harness_run_backtest(
        strategy=strategy,
        params=params,
        source=source,
        time_range=time_range,
        db=db,
        strategy_id=strategy_id,
    )


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

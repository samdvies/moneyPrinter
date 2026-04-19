"""Single-iteration research loop runner."""

from __future__ import annotations

import logging
from uuid import uuid4

from algobet_common.bus import BusClient
from algobet_common.config import Settings
from algobet_common.db import Database
from strategy_registry import crud
from strategy_registry.models import Status

from .workflow import hypothesize, promote, run_backtest

logger = logging.getLogger(__name__)


async def run_once(db: Database, bus: BusClient, settings: Settings) -> None:
    """Execute one iteration of the research loop.

    Sequence:
    1. Generate a hypothesis (stub).
    2. Create a strategy in the registry (hypothesis status).
    3. Run a backtest (stub).
    4. If the backtest status is 'stub', advance: hypothesis → backtesting → paper.
    5. Log the final strategy status.

    The orchestrator does NOT attempt paper → awaiting-approval.
    That decision is reserved for a human via the dashboard.
    """
    hypothesis = await hypothesize()

    slug = f"{hypothesis['name']}-{uuid4().hex[:8]}"
    strategy = await crud.create_strategy(db, slug=slug)
    logger.info("run_once: created strategy %s (id=%s)", slug, strategy.id)

    result = await run_backtest(hypothesis)

    if result.get("status") == "stub":
        strategy = await promote(db, bus, strategy.id, Status.BACKTESTING)
        strategy = await promote(db, bus, strategy.id, Status.PAPER)

    logger.info(
        "run_once: complete — strategy %s final status=%s",
        strategy.slug,
        strategy.status,
    )

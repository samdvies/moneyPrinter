"""Single-iteration research loop runner."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

from algobet_common.bus import BusClient
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import MarketData, Venue
from backtest_engine.sources.synthetic import SyntheticSource
from backtest_engine.strategies import trivial as trivial_strategy
from backtest_engine.strategy_protocol import StrategyModule
from strategy_registry import crud
from strategy_registry.models import Status

from .workflow import hypothesize, promote, run_backtest

logger = logging.getLogger(__name__)

# Synthetic tick config: 10 ticks one minute apart, best ask 1.40 so the
# trivial strategy fires on every tick (its threshold is <= 1.50). 6b replaces
# this entire block with an ``ArchiveSource`` + a research-generated strategy.
_SYNTHETIC_N_TICKS = 10
_SYNTHETIC_BEST_ASK = Decimal("1.40")
_SYNTHETIC_BEST_BID = Decimal("1.30")
_SYNTHETIC_SIZE = Decimal("100")


def _build_synthetic_ticks(market_id: str) -> list[MarketData]:
    """Build a short, fully-filling synthetic tick sequence.

    Timestamps are spaced one minute apart starting at ``datetime.now(UTC)``
    so the time_range passed to the harness comfortably brackets every tick.
    """
    now = datetime.now(UTC)
    return [
        MarketData(
            venue=Venue.BETFAIR,
            market_id=market_id,
            timestamp=now + timedelta(minutes=i),
            bids=[(_SYNTHETIC_BEST_BID, _SYNTHETIC_SIZE)],
            asks=[(_SYNTHETIC_BEST_ASK, _SYNTHETIC_SIZE)],
        )
        for i in range(_SYNTHETIC_N_TICKS)
    ]


async def run_once(db: Database, bus: BusClient, settings: Settings) -> None:
    """Execute one iteration of the research loop.

    Sequence:
    1. Generate a hypothesis (stub).
    2. Create a strategy in the registry (hypothesis status).
    3. Build a synthetic ``SyntheticSource`` + the trivial reference strategy
       and run a real backtest via ``run_backtest`` (harness-backed).
    4. If the backtest produced any trades, advance: hypothesis → backtesting
       → paper. The advance condition is ``n_trades > 0`` — Sharpe can be 0.0
       on zero-edge fills (6a uses trivial immediate-fill settlement), so the
       trade count is the robust signal that the harness actually ran.
    5. Log the final strategy status.

    The orchestrator does NOT attempt paper → awaiting-approval. That
    decision is reserved for a human via the dashboard.
    """
    del settings  # reserved for future use (claude-api client etc.)

    hypothesis = await hypothesize()

    slug = f"{hypothesis['name']}-{uuid4().hex[:8]}"
    strategy = await crud.create_strategy(db, slug=slug)
    logger.info("run_once: created strategy %s (id=%s)", slug, strategy.id)

    market_id = f"synthetic.{slug}"
    ticks = _build_synthetic_ticks(market_id)
    source = SyntheticSource(ticks)
    time_range = (ticks[0].timestamp, ticks[-1].timestamp)

    # The trivial strategy is a module exposing ``on_tick`` at module level;
    # the ``StrategyModule`` Protocol is structural, so the module object
    # itself satisfies the contract. Cast keeps mypy narrowing the kwarg.
    strategy_module = cast(StrategyModule, trivial_strategy)

    result = await run_backtest(
        strategy.id,
        strategy_module,
        {},
        source,
        time_range,
        db,
    )

    # TODO(6b): replace this trivial gate with a real edge check. The current
    # synthetic source (best ask 1.40) fires the trivial strategy (threshold
    # ≤ 1.50) on every tick, so n_trades > 0 is almost guaranteed and the
    # gate is a rubber-stamp. Phase 6b supplies an ArchiveSource + a
    # research-generated strategy with a meaningful negative-path data set,
    # making it possible for this branch to legitimately reject a hypothesis.
    if result["n_trades"] > 0:
        strategy = await promote(db, bus, strategy.id, Status.BACKTESTING)
        strategy = await promote(db, bus, strategy.id, Status.PAPER)
    else:
        logger.warning(
            "run_once: backtest produced 0 trades for %s; leaving at status=%s",
            strategy.slug,
            strategy.status,
        )

    logger.info(
        "run_once: complete — strategy %s final status=%s",
        strategy.slug,
        strategy.status,
    )

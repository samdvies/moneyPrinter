"""Single-iteration research loop runner.

Phase 6b.4 wiring: the runner no longer uses the rigged trivial strategy +
best-ask-1.40 synthetic source. Instead it:

1. Loads the reference mean-reversion strategy from
   ``wiki/30-Strategies/mean-reversion-ref.md`` via
   ``strategy_registry.wiki_loader.load_strategy_from_wiki`` (idempotent
   upsert — the strategy row survives across ``run_once`` invocations).
2. Builds a deterministic AR(1) mean-reverting tick series.
3. Dispatches the real harness via ``workflow.run_backtest``.
4. Advances to paper only if ``n_trades > 0`` AND ``total_pnl_gbp > 0``.

The AR(1) tick builder is exposed at module level so the integration tests
can monkey-patch it to force a trending series for the negative path.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from algobet_common.bus import BusClient
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import MarketData, Venue
from backtest_engine.sources.synthetic import SyntheticSource
from backtest_engine.strategies import mean_reversion as mean_reversion_strategy
from backtest_engine.strategy_protocol import StrategyModule
from strategy_registry.models import Status
from strategy_registry.wiki_loader import load_strategy_from_wiki

from .workflow import promote, run_backtest

logger = logging.getLogger(__name__)

# Resolve repo root once at import time.  ``runner.py`` lives at
# ``services/research_orchestrator/src/research_orchestrator/runner.py``
# so the repo root is five ``.parent`` hops up.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_REFERENCE_WIKI_PATH = _REPO_ROOT / "wiki" / "30-Strategies" / "mean-reversion-ref.md"

# Default synthetic-series parameters.  300 ticks comfortably exceeds the
# 30-tick warm-up window in the reference strategy, leaving ~270 ticks over
# which the mean-reversion edge can accumulate.
_DEFAULT_N_TICKS = 300
_DEFAULT_MEAN = Decimal("2.00")
_DEFAULT_PULL = 0.4
_DEFAULT_NOISE = 0.05
_DEFAULT_DRIFT = Decimal("0")
_DEFAULT_SEED = 42
_DEFAULT_SPREAD = Decimal("0.02")


def _build_mean_reverting_ticks(
    n_ticks: int = _DEFAULT_N_TICKS,
    *,
    mean: Decimal = _DEFAULT_MEAN,
    pull: float = _DEFAULT_PULL,
    noise: float = _DEFAULT_NOISE,
    drift: Decimal = _DEFAULT_DRIFT,
    seed: int = _DEFAULT_SEED,
    spread: Decimal = _DEFAULT_SPREAD,
    market_id: str = "synthetic.mean-reversion-ref",
) -> list[MarketData]:
    """Build a deterministic AR(1) mid-price series.

    Model:  price_{t+1} = mean + (1 - pull) * (price_t - mean) + drift + N(0, noise)

    - ``pull=0.4``: strong reversion toward ``mean`` — prices that wander
      far above/below are pulled back quickly.  The reference strategy
      profits on this regime.
    - ``drift > 0``: biases each step upward regardless of distance from
      the mean.  With ``pull`` small enough, drift dominates and the
      series trends; the reference strategy loses on this regime.

    The series is seeded (default ``seed=42``) so two independent calls
    with identical arguments produce identical tick lists — necessary for
    the determinism contract the orchestrator inherits from the harness.

    Each tick carries a single bid/ask level at ``mid ± spread/2``, sized
    at 100 GBP so the strategy's 10 GBP default stake always fills.
    """
    rng = random.Random(seed)
    base_timestamp = datetime.now(UTC)
    mean_f = float(mean)
    drift_f = float(drift)
    price = mean_f
    half_spread = spread / Decimal(2)
    ticks: list[MarketData] = []
    for i in range(n_ticks):
        price = mean_f + (1.0 - pull) * (price - mean_f) + drift_f + rng.gauss(0, noise)
        # Clamp to a sensible Betfair-style price floor so the book never
        # goes negative or below the minimum odds.
        if price <= 1.01:
            price = 1.01
        mid = Decimal(str(round(price, 4)))
        ticks.append(
            MarketData(
                venue=Venue.BETFAIR,
                market_id=market_id,
                timestamp=base_timestamp + timedelta(seconds=i),
                bids=[(mid - half_spread, Decimal("100"))],
                asks=[(mid + half_spread, Decimal("100"))],
            )
        )
    return ticks


async def run_once(db: Database, bus: BusClient, settings: Settings) -> None:
    """Execute one iteration of the research loop.

    Sequence:
    1. Load (UPSERT) the reference strategy row from
       ``wiki/30-Strategies/mean-reversion-ref.md``.  Status is never
       clobbered by the loader — the lifecycle state machine is the sole
       writer of ``strategies.status``.
    2. Build a deterministic mean-reverting ``SyntheticSource``.
    3. Dispatch the real harness via ``workflow.run_backtest``, which
       seals a ``strategy_runs`` row with the fixed-shape metrics dict.
    4. Advance hypothesis → backtesting → paper only if the strategy
       genuinely produced positive realised P&L:
          ``n_trades > 0 AND total_pnl_gbp > 0``
       On a strongly trending series (see the negative-path integration
       test) the strategy bleeds and the gate rejects.
    5. Log the final strategy status.

    The orchestrator does NOT attempt paper → awaiting-approval.  That
    decision is reserved for a human via the dashboard.
    """
    del settings  # reserved for future use (Claude-API client etc.)

    strategy = await load_strategy_from_wiki(_REFERENCE_WIKI_PATH, db)
    logger.info(
        "run_once: loaded reference strategy %s (id=%s, status=%s)",
        strategy.slug,
        strategy.id,
        strategy.status.value,
    )

    ticks = _build_mean_reverting_ticks()
    source = SyntheticSource(ticks)
    time_range = (ticks[0].timestamp, ticks[-1].timestamp)

    # Hand the strategy its on-disk parameters as a fresh dict so the
    # mutable ``_window`` state does not leak across runs.  The module
    # satisfies the structural ``StrategyModule`` Protocol by exposing
    # ``on_tick`` at module level.
    params = dict(strategy.parameters or {})
    strategy_module = cast(StrategyModule, mean_reversion_strategy)

    result = await run_backtest(
        strategy.id,
        strategy_module,
        params,
        source,
        time_range,
        db,
    )

    # Full metrics line for operator debugging — easier to diagnose a run
    # that did not advance without having to tail the harness logs.
    logger.info("run_once: backtest result = %s", result)

    # Advancement gate: both a non-zero trade count AND positive realised
    # P&L.  The delta-P&L settlement in the harness guarantees this gate
    # is reachable — on a trending series it returns <= 0, leaving the
    # strategy at ``hypothesis``.
    if result["n_trades"] > 0 and result["total_pnl_gbp"] > Decimal("0"):
        strategy = await promote(db, bus, strategy.id, Status.BACKTESTING)
        strategy = await promote(db, bus, strategy.id, Status.PAPER)
    else:
        logger.warning(
            "run_once: backtest gate not cleared for %s "
            "(n_trades=%s, total_pnl_gbp=%s); leaving at status=%s",
            strategy.slug,
            result["n_trades"],
            result["total_pnl_gbp"],
            strategy.status,
        )

    logger.info(
        "run_once: complete — strategy %s final status=%s",
        strategy.slug,
        strategy.status,
    )

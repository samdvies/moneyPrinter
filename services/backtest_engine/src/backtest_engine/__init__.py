"""Backtest harness — replays MarketData ticks through the fill engine.

Public surface:
- ``run_backtest`` — the harness entry point (see ``harness``).
- ``StrategyModule`` — the strategy protocol (see ``strategy_protocol``).
- ``TickSource`` / ``SyntheticSource`` / ``ArchiveSource`` — tick sources
  (see ``sources``).
- ``BacktestResult`` — the fixed-shape metrics dict (see ``harness``).
"""

from __future__ import annotations

from backtest_engine.harness import BacktestResult, run_backtest
from backtest_engine.sources.archive import ArchiveSource
from backtest_engine.sources.synthetic import SyntheticSource
from backtest_engine.strategy_protocol import StrategyModule, TickSource

__all__ = [
    "ArchiveSource",
    "BacktestResult",
    "StrategyModule",
    "SyntheticSource",
    "TickSource",
    "run_backtest",
]

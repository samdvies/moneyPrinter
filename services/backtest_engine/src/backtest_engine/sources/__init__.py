"""Concrete ``TickSource`` implementations.

- ``SyntheticSource`` — in-memory list of ticks; used for determinism tests
  and orchestrator smoke runs until 6b lands a real corpus.
- ``ArchiveSource`` — Timescale cursor over ``market_data_archive``.
"""

from __future__ import annotations

from backtest_engine.sources.archive import ArchiveSource
from backtest_engine.sources.synthetic import SyntheticSource

__all__ = ["ArchiveSource", "SyntheticSource"]

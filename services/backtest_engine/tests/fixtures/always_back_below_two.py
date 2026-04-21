"""Trivial BACK-only strategy used by the determinism pin in test_harness.

This module now re-exports ``on_tick`` from the production location
``backtest_engine.strategies.trivial``. The fixture path is kept because
``test_harness.py`` imports it via the ``fixtures`` top-level name (see
``tests/conftest.py``), and moving that import would ripple through the
mypy override. The re-export keeps a single source of truth for the
strategy body while preserving the fixture import path.
"""

from __future__ import annotations

from backtest_engine.strategies.trivial import on_tick

__all__ = ["on_tick"]

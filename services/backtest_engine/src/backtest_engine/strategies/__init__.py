"""Reference / trivial strategies bundled with the backtest engine.

These are not research-generated strategies — they exist so that the harness,
the orchestrator smoke loop, and determinism tests have a minimal fixture
that satisfies the ``StrategyModule`` Protocol. Phase 6b will replace the
orchestrator's use of these with real research-generated strategies.
"""

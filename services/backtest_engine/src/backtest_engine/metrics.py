"""Pure metric helpers for the backtest harness.

Four named functions, each a pure function of its arguments — no I/O, no
global state, no hidden randomness. The harness drives them.

Return types are JSON-serialisable via ``json.dumps(default=str)`` so the
resulting ``BacktestResult`` dict can be stored directly in the
``strategy_runs.metrics`` jsonb column (see
``strategy_registry/crud.py::end_run``).

``_trivial_settlement`` is module-private: 6a uses it as the default
settlement (every fill P&L = 0) so the harness control flow can be
exercised without pretending to price risk. 6b swaps settlement by
passing a caller-supplied ``settlement_fn`` to ``total_pnl_gbp`` and
``win_rate`` — the private default never needs to be imported by name
outside of tests that specifically pin its behaviour.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from decimal import Decimal

from algobet_common.schemas import ExecutionResult

__all__ = [
    "SettlementFn",
    "max_drawdown_gbp",
    "sharpe",
    "total_pnl_gbp",
    "win_rate",
]

# Annualisation factor for daily-bucketed Sharpe — matches the standard
# 252 trading-day convention used across the quant literature.
_ANNUAL_FACTOR = 252

# Settlement function signature: given the filled result, return settled P&L
# in GBP at tick close. Phase 6a uses a trivial settlement (every fill settles
# at its own VWAP, so P&L = 0); 6b will replace this with real market-close
# settlement when the reference strategy lands.
SettlementFn = Callable[[ExecutionResult], Decimal]


def _trivial_settlement(_result: ExecutionResult) -> Decimal:
    """Module-private default settlement: every fill settles at its own VWAP.

    P&L is therefore zero for every matched order. Kept as the default
    argument for ``total_pnl_gbp`` / ``win_rate`` so 6a can exercise the
    full control flow; 6b replaces it by passing a real ``settlement_fn``
    rather than editing this function's body.
    """
    return Decimal("0")


def total_pnl_gbp(
    fills: Sequence[ExecutionResult],
    settlement_fn: SettlementFn = _trivial_settlement,
) -> Decimal:
    """Sum ``settlement_fn(fill)`` across every fill with non-zero stake.

    Resting (``filled_stake == 0``) results are ignored — they are not fills.
    """
    total = Decimal("0")
    for fill in fills:
        if fill.filled_stake <= Decimal("0"):
            continue
        total += settlement_fn(fill)
    return total


def sharpe(per_tick_pnl_series: Sequence[Decimal]) -> float:
    """Annualised Sharpe ratio over a tick-level P&L series.

    Each element of ``per_tick_pnl_series`` is treated as one sample. The
    annualisation factor (252) is applied regardless of sample cadence —
    callers supplying sparse per-day P&L get a standard daily Sharpe;
    callers supplying dense tick-level P&L get a number whose annualisation
    is only meaningful if the total span is a standard trading session
    length. Proper per-UTC-day bucketing is deferred to 6b when the
    reference strategy produces timestamped P&L.

    Returns 0.0 on degenerate inputs (empty, single, zero stddev) —
    JSONB cannot round-trip NaN.
    """
    if len(per_tick_pnl_series) < 2:
        return 0.0
    floats = [float(x) for x in per_tick_pnl_series]
    mean = sum(floats) / len(floats)
    variance = sum((x - mean) ** 2 for x in floats) / (len(floats) - 1)
    if variance <= 0:
        return 0.0
    std = math.sqrt(variance)
    return (mean / std) * math.sqrt(_ANNUAL_FACTOR)


def max_drawdown_gbp(equity_curve: Sequence[Decimal]) -> Decimal:
    """Worst peak-to-trough drawdown, returned as a non-negative Decimal.

    An empty curve returns ``Decimal("0")``. A monotonically rising curve
    also returns ``Decimal("0")``.
    """
    if not equity_curve:
        return Decimal("0")
    peak = equity_curve[0]
    worst = Decimal("0")
    for value in equity_curve:
        if value > peak:
            peak = value
        drawdown = peak - value
        if drawdown > worst:
            worst = drawdown
    return worst


def win_rate(
    fills: Sequence[ExecutionResult],
    settlement_fn: SettlementFn = _trivial_settlement,
) -> float:
    """Fraction of fills with settled P&L > 0 under ``settlement_fn``.

    The default trivial settlement returns 0 for every fill, so ``win_rate``
    is 0.0 whenever any fill exists. 6b swaps settlement by passing a
    caller argument — no edits to this function are required.
    """
    matched = [f for f in fills if f.filled_stake > Decimal("0")]
    if not matched:
        return 0.0
    wins = sum(1 for f in matched if settlement_fn(f) > Decimal("0"))
    return wins / len(matched)

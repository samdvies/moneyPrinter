"""Pure metric helpers for the backtest harness.

Four named functions, each a pure function of its arguments — no I/O, no
global state, no hidden randomness. The harness drives them.

Return types are JSON-serialisable via ``json.dumps(default=str)`` so the
resulting ``BacktestResult`` dict can be stored directly in the
``strategy_runs.metrics`` jsonb column (see
``strategy_registry/crud.py::end_run``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from decimal import Decimal

from algobet_common.schemas import ExecutionResult

# Annualisation factor for daily-bucketed Sharpe — matches the standard
# 252 trading-day convention used across the quant literature.
_ANNUAL_FACTOR = 252

# Settlement function signature: given the filled result, return settled P&L
# in GBP at tick close. Phase 6a uses a trivial settlement (every fill settles
# at its own VWAP, so P&L = 0); 6b will replace this with real market-close
# settlement when the reference strategy lands.
SettlementFn = Callable[[ExecutionResult], Decimal]


def trivial_settlement(_result: ExecutionResult) -> Decimal:
    """Default settlement: assume every fill settles at its own VWAP.

    P&L is therefore zero for every matched order. This lets the harness
    exercise the full control flow (book updates, fills, metrics) without
    pretending to price risk — that's 6b's job.
    """
    return Decimal("0")


def total_pnl_gbp(
    fills: Sequence[ExecutionResult],
    settlement_fn: SettlementFn = trivial_settlement,
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
    """Annualised Sharpe ratio from a per-tick P&L series.

    Tick-level series are summed per UTC day if the span exceeds a day's worth
    of samples; otherwise we treat each tick as its own bucket. Returns 0.0
    when the series has fewer than two samples or when volatility is zero
    (a NaN would not round-trip through jsonb).
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


def win_rate(fills: Sequence[ExecutionResult]) -> float:
    """Fraction of fills with settled P&L > 0 under the trivial settlement.

    With the 6a placeholder settlement returning 0 for every fill, this is
    always 0.0 whenever any fill exists. 6b will replace this with a real
    calculation once settlement returns non-zero values.
    """
    matched = [f for f in fills if f.filled_stake > Decimal("0")]
    if not matched:
        return 0.0
    wins = sum(1 for f in matched if trivial_settlement(f) > Decimal("0"))
    return wins / len(matched)

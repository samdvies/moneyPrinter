"""Pure metric helpers for the backtest harness.

Four named functions, each a pure function of its arguments — no I/O, no
global state, no hidden randomness. The harness drives them.

Return types are JSON-serialisable via ``json.dumps(default=str)`` so the
resulting ``BacktestResult`` dict can be stored directly in the
``strategy_runs.metrics`` jsonb column (see
``strategy_registry/crud.py::end_run``).

``_trivial_settlement`` is module-private: 6a uses it as the default
settlement (every fill P&L = 0) so the harness control flow can be
exercised without pretending to price risk. 6b introduces
``build_delta_pnl_settlement``: a stateful settlement *factory* that
returns a per-run closure, tracking positions per
``(venue, market_id, selection_id)`` across fills and emitting realised
P&L on opposite-side closes. The harness builds one closure per run,
calls it once per fill (requires both the triggering ``OrderSignal`` and
the resulting ``ExecutionResult``), and records the per-fill realised
P&L alongside the fill. ``total_pnl_gbp_from_pnls`` /
``win_rate_from_pnls`` then sum / count those recorded Decimals — a
single source of truth for realised P&L per run.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from decimal import Decimal

from algobet_common.schemas import ExecutionResult, OrderSide, OrderSignal

__all__ = [
    "DeltaSettlementFn",
    "SettlementFn",
    "build_delta_pnl_settlement",
    "max_drawdown_gbp",
    "sharpe",
    "total_pnl_gbp",
    "total_pnl_gbp_from_pnls",
    "win_rate",
    "win_rate_from_pnls",
]

# Annualisation factor for daily-bucketed Sharpe — matches the standard
# 252 trading-day convention used across the quant literature.
_ANNUAL_FACTOR = 252

# Legacy single-arg settlement signature — retained for the 6a trivial
# default and for tests that pin custom per-fill settlements.
SettlementFn = Callable[[ExecutionResult], Decimal]

# 6b stateful settlement signature. The closure returned by
# ``build_delta_pnl_settlement`` carries per-(venue, market_id, selection_id)
# position state across fills, so it must see the ``OrderSignal`` (for
# side / venue / market_id / selection_id) alongside the ``ExecutionResult``
# (for filled_stake / filled_price). Unfilled results contribute Decimal("0").
DeltaSettlementFn = Callable[[OrderSignal, ExecutionResult], Decimal]


def _trivial_settlement(_result: ExecutionResult) -> Decimal:
    """Module-private default settlement: every fill settles at its own VWAP.

    P&L is therefore zero for every matched order. Retained for back-compat
    with 6a tests and as the default argument on the legacy ``total_pnl_gbp``
    / ``win_rate`` helpers. 6b's harness uses ``build_delta_pnl_settlement``
    exclusively.
    """
    return Decimal("0")


# ---------------------------------------------------------------------------
# Delta-P&L settlement factory (6b)
# ---------------------------------------------------------------------------


def _side_sign(side: OrderSide) -> int:
    """Return +1 for BACK/YES (long), -1 for LAY/NO (short)."""
    if side in (OrderSide.BACK, OrderSide.YES):
        return 1
    return -1


def build_delta_pnl_settlement() -> DeltaSettlementFn:
    """Return a stateful settlement closure for a single backtest run.

    Tracks net position per ``(venue, market_id, selection_id)`` across
    fills. On every fill the closure:

    - Returns ``Decimal("0")`` for unfilled results (``filled_stake == 0``
      or missing ``filled_price``) — resting orders do not realise P&L.
    - On a same-side fill, extends the position (weighted-average entry
      price update) and returns ``Decimal("0")``.
    - On an opposite-side fill, realises P&L against the closing size
      (``min(|new_stake|, |prior_position|)``):
        - BACK-then-LAY: realised = closing_size * (lay_price - back_entry)
        - LAY-then-BACK: realised = closing_size * (lay_entry - back_price)
      Any residual on the new side (if ``|new_stake| > |prior_position|``)
      becomes the new open position at ``filled_price``.

    This is the "simplified delta-P&L" committed to by the Phase 6b plan
    ("an opposite-side fill closes the prior position at the new fill
    price"). No market-close settlement, no commission. Real settlement
    is deferred to post-6c.

    The closure is NOT reusable across runs — instantiate a fresh closure
    per ``run_backtest`` invocation.
    """
    # Per-market state: key is (venue, market_id, selection_id). Value is
    # (signed_position, entry_price). ``signed_position`` is positive for a
    # net BACK/YES exposure, negative for LAY/NO. ``entry_price`` is the
    # volume-weighted-average entry for the open position; undefined (None)
    # when there is no open position.
    positions: dict[tuple[str, str, str | None], tuple[Decimal, Decimal]] = {}

    def _settle(signal: OrderSignal, result: ExecutionResult) -> Decimal:
        if result.filled_stake <= Decimal("0") or result.filled_price is None:
            return Decimal("0")

        key = (str(signal.venue), signal.market_id, signal.selection_id)
        new_sign = _side_sign(signal.side)
        new_size = result.filled_stake
        new_price = result.filled_price

        prior = positions.get(key)
        if prior is None or prior[0] == Decimal("0"):
            # Open a fresh position.
            positions[key] = (Decimal(new_sign) * new_size, new_price)
            return Decimal("0")

        prior_signed, prior_entry = prior
        prior_sign = 1 if prior_signed > 0 else -1

        if new_sign == prior_sign:
            # Same-side extension: weighted-average entry.
            prior_size = abs(prior_signed)
            total_size = prior_size + new_size
            new_entry = ((prior_entry * prior_size) + (new_price * new_size)) / total_size
            positions[key] = (Decimal(prior_sign) * total_size, new_entry)
            return Decimal("0")

        # Opposite side: realise P&L against the closing portion.
        prior_size = abs(prior_signed)
        closing_size = min(new_size, prior_size)

        # Delta P&L convention (Phase 6b plan §"P&L settlement for 6b"):
        #   BACK-then-LAY:  realised = closing_size * (back_entry - lay_price)
        #                   (profit when we BACK'd cheap and LAY out higher)
        #   LAY-then-BACK:  realised = closing_size * (lay_entry  - back_price)
        #                   (profit when we LAY'd high and BACK out lower — the
        #                   spec's "symmetric" case with sign reflected)
        # Both expressions collapse to ``prior_entry - new_price`` because the
        # closing fill is always the opposite side of the open position.
        realised = closing_size * (prior_entry - new_price)

        residual_prior = prior_size - closing_size
        residual_new = new_size - closing_size

        if residual_prior > Decimal("0"):
            # Partial close: prior position persists at its original entry.
            positions[key] = (Decimal(prior_sign) * residual_prior, prior_entry)
        elif residual_new > Decimal("0"):
            # Full close + residual flips to the new side at new_price.
            positions[key] = (Decimal(new_sign) * residual_new, new_price)
        else:
            # Exact close: position flat.
            positions[key] = (Decimal("0"), Decimal("0"))

        return realised

    return _settle


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def total_pnl_gbp(
    fills: Sequence[ExecutionResult],
    settlement_fn: SettlementFn = _trivial_settlement,
) -> Decimal:
    """Sum ``settlement_fn(fill)`` across every fill with non-zero stake.

    Resting (``filled_stake == 0``) results are ignored — they are not fills.

    Retained for the 6a trivial-settlement call sites and for unit tests
    that pin custom single-arg settlements. The 6b harness instead records
    per-fill realised P&L via ``build_delta_pnl_settlement`` and aggregates
    with ``total_pnl_gbp_from_pnls``.
    """
    total = Decimal("0")
    for fill in fills:
        if fill.filled_stake <= Decimal("0"):
            continue
        total += settlement_fn(fill)
    return total


def total_pnl_gbp_from_pnls(realised_pnls: Sequence[Decimal]) -> Decimal:
    """Sum pre-computed per-fill realised P&L values.

    Harness fast path: the delta-P&L closure records one Decimal per fill
    during replay; this helper just sums them. Single source of truth for
    realised P&L — no re-invocation of the settlement closure, no risk of
    divergence between equity-curve and terminal totals.
    """
    return sum(realised_pnls, Decimal("0"))


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
    is 0.0 whenever any fill exists. Retained for 6a trivial-settlement
    call sites and custom-settlement unit tests; the 6b harness uses
    ``win_rate_from_pnls`` against recorded delta-P&L values.
    """
    matched = [f for f in fills if f.filled_stake > Decimal("0")]
    if not matched:
        return 0.0
    wins = sum(1 for f in matched if settlement_fn(f) > Decimal("0"))
    return wins / len(matched)


def win_rate_from_pnls(realised_pnls: Sequence[Decimal]) -> float:
    """Fraction of pre-computed per-fill realised P&Ls that are strictly positive.

    Only values corresponding to genuine fills should be passed in — the
    harness records Decimal("0") for unfilled (resting) results AND for
    opening / extending positions. Both are excluded from the wins-rate
    denominator: a "fill" for rate purposes is a realised round-trip,
    i.e. any entry with non-zero realised P&L. This differs from the
    legacy ``win_rate`` (which counts all matched orders) and is the
    correct interpretation for delta-P&L settlement where only closing
    fills realise.
    """
    closed = [p for p in realised_pnls if p != Decimal("0")]
    if not closed:
        return 0.0
    wins = sum(1 for p in closed if p > Decimal("0"))
    return wins / len(closed)

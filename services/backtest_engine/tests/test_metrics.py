"""Unit tests for the pure metrics module.

``_trivial_settlement`` is module-private — callers rely on the default
argument of ``total_pnl_gbp`` / ``win_rate`` rather than importing it by
name. Only ``test_win_rate_with_custom_settlement`` + the smoke test for
the private default exercise the underscore name directly, which is the
one legitimate reason to reach past the underscore.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

from algobet_common.schemas import ExecutionResult, OrderSide, OrderSignal, Venue
from backtest_engine.metrics import (
    _trivial_settlement,
    build_delta_pnl_settlement,
    max_drawdown_gbp,
    sharpe,
    total_pnl_gbp,
    total_pnl_gbp_from_pnls,
    win_rate,
    win_rate_from_pnls,
)


def _fill(filled_stake: str = "10", filled_price: str | None = "2.00") -> ExecutionResult:
    return ExecutionResult(
        order_id="00000000-0000-0000-0000-000000000001",
        strategy_id="strat-001",
        mode="paper",
        status="filled",
        filled_stake=Decimal(filled_stake),
        filled_price=Decimal(filled_price) if filled_price is not None else None,
        timestamp=datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
    )


def _resting() -> ExecutionResult:
    return ExecutionResult(
        order_id="00000000-0000-0000-0000-000000000002",
        strategy_id="strat-001",
        mode="paper",
        status="placed",
        filled_stake=Decimal("0"),
        filled_price=None,
        timestamp=datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
    )


def test_total_pnl_trivial_settlement_is_zero() -> None:
    # Rely on the module-private default settlement rather than importing it.
    fills = [_fill(), _fill(filled_stake="5")]
    assert total_pnl_gbp(fills) == Decimal("0")


def test_total_pnl_custom_settlement_sums() -> None:
    fills = [_fill(), _fill(filled_stake="5")]
    result = total_pnl_gbp(fills, lambda _f: Decimal("2.50"))
    assert result == Decimal("5.00")


def test_total_pnl_skips_resting_orders() -> None:
    fills = [_resting(), _fill()]
    result = total_pnl_gbp(fills, lambda _f: Decimal("3"))
    assert result == Decimal("3")


def test_total_pnl_empty_returns_zero() -> None:
    assert total_pnl_gbp([]) == Decimal("0")


def test_sharpe_empty_returns_zero() -> None:
    assert sharpe([]) == 0.0


def test_sharpe_single_sample_returns_zero() -> None:
    assert sharpe([Decimal("1")]) == 0.0


def test_sharpe_constant_series_returns_zero() -> None:
    assert sharpe([Decimal("1")] * 10) == 0.0


def test_sharpe_varied_series_is_finite_and_annualised() -> None:
    series = [Decimal("1"), Decimal("-1"), Decimal("2"), Decimal("-2")]
    result = sharpe(series)
    assert isinstance(result, float)
    assert math.isfinite(result)


def test_sharpe_determinism_identical_inputs() -> None:
    series = [Decimal("1"), Decimal("2"), Decimal("-1"), Decimal("0.5")]
    assert sharpe(series) == sharpe(series)


def test_max_drawdown_empty_is_zero() -> None:
    assert max_drawdown_gbp([]) == Decimal("0")


def test_max_drawdown_monotone_up_is_zero() -> None:
    curve = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("5")]
    assert max_drawdown_gbp(curve) == Decimal("0")


def test_max_drawdown_single_trough() -> None:
    curve = [Decimal("10"), Decimal("5"), Decimal("7"), Decimal("12")]
    assert max_drawdown_gbp(curve) == Decimal("5")


def test_max_drawdown_worst_of_two_troughs() -> None:
    curve = [
        Decimal("10"),
        Decimal("8"),  # -2 from 10
        Decimal("15"),
        Decimal("5"),  # -10 from 15 (worst)
        Decimal("11"),
    ]
    assert max_drawdown_gbp(curve) == Decimal("10")


def test_win_rate_empty_is_zero() -> None:
    assert win_rate([]) == 0.0


def test_win_rate_only_resting_is_zero() -> None:
    assert win_rate([_resting(), _resting()]) == 0.0


def test_win_rate_trivial_settlement_zero_since_no_pnl() -> None:
    # Default trivial settlement returns 0 for every fill -> no wins.
    assert win_rate([_fill(), _fill()]) == 0.0


def test_win_rate_private_default_is_trivial_zero() -> None:
    # Pin the module-private default's behaviour so 6b can't silently
    # regress the placeholder. This is the one legitimate reason to reach
    # past the underscore by name.
    assert _trivial_settlement(_fill()) == Decimal("0")


def test_win_rate_with_custom_settlement() -> None:
    # Three fills: two winners (+1), one loser (-1) under a stake-parity
    # settlement. Win rate must be 2/3 — proves ``win_rate`` actually
    # honours the ``settlement_fn`` argument rather than hard-coding the
    # trivial default.
    winners = [_fill(filled_stake="10"), _fill(filled_stake="5")]
    loser = _fill(filled_stake="7")
    fills = [*winners, loser]

    def _stake_parity(f: ExecutionResult) -> Decimal:
        if f.filled_stake == Decimal("10") or f.filled_stake <= Decimal("5"):
            return Decimal("1")
        return Decimal("-1")

    result = win_rate(fills, _stake_parity)
    assert result == 2 / 3
    assert result > 0.0


# ---------------------------------------------------------------------------
# build_delta_pnl_settlement — 6b stateful delta-P&L closure
# ---------------------------------------------------------------------------


def _signal(
    side: OrderSide,
    stake: str,
    price: str,
    *,
    market_id: str = "1.234567",
    venue: Venue = Venue.BETFAIR,
    selection_id: str | None = None,
) -> OrderSignal:
    return OrderSignal(
        strategy_id="strat-001",
        mode="paper",
        venue=venue,
        market_id=market_id,
        side=side,
        stake=Decimal(stake),
        price=Decimal(price),
        selection_id=selection_id,
    )


def _filled(stake: str, price: str) -> ExecutionResult:
    return ExecutionResult(
        order_id="00000000-0000-0000-0000-000000000001",
        strategy_id="strat-001",
        mode="paper",
        status="filled",
        filled_stake=Decimal(stake),
        filled_price=Decimal(price),
        timestamp=datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
    )


def test_build_delta_pnl_settlement_realises_on_close() -> None:
    """BACK 10 @ 2.00 then LAY 10 @ 1.80 → realised = 10 * (2.00 - 1.80) = +2.00."""
    settle = build_delta_pnl_settlement()
    assert settle(_signal(OrderSide.BACK, "10", "2.00"), _filled("10", "2.00")) == Decimal("0")
    realised = settle(_signal(OrderSide.LAY, "10", "1.80"), _filled("10", "1.80"))
    assert realised == Decimal("2.00")


def test_build_delta_pnl_settlement_loss_on_close() -> None:
    settle = build_delta_pnl_settlement()
    settle(_signal(OrderSide.BACK, "10", "2.00"), _filled("10", "2.00"))
    realised = settle(_signal(OrderSide.LAY, "10", "2.20"), _filled("10", "2.20"))
    # BACK @ 2.00 then LAY @ 2.20: 10 * (2.00 - 2.20) = -2.00 GBP loss.
    assert realised == Decimal("-2.00")


def test_build_delta_pnl_settlement_lay_first() -> None:
    settle = build_delta_pnl_settlement()
    settle(_signal(OrderSide.LAY, "10", "2.00"), _filled("10", "2.00"))
    realised = settle(_signal(OrderSide.BACK, "10", "1.80"), _filled("10", "1.80"))
    # LAY @ 2.00 then BACK @ 1.80: 10 * (2.00 - 1.80) = 2.00 GBP profit.
    assert realised == Decimal("2.00")


def test_build_delta_pnl_settlement_same_side_extends_position() -> None:
    settle = build_delta_pnl_settlement()
    # BACK 10 @ 2.00, then BACK 10 @ 1.90 — no close, no realised P&L.
    assert settle(_signal(OrderSide.BACK, "10", "2.00"), _filled("10", "2.00")) == Decimal("0")
    assert settle(_signal(OrderSide.BACK, "10", "1.90"), _filled("10", "1.90")) == Decimal("0")
    # Weighted-average entry: (10*2.00 + 10*1.90) / 20 = 1.95.
    # Now close with LAY 20 @ 1.80 — profit = 20 * (1.95 - 1.80) = 3.00.
    realised = settle(_signal(OrderSide.LAY, "20", "1.80"), _filled("20", "1.80"))
    assert realised == Decimal("3.00")


def test_build_delta_pnl_settlement_partial_close() -> None:
    settle = build_delta_pnl_settlement()
    # BACK 20 @ 2.00, then partial LAY 10 @ 1.80 closes half at +0.20.
    settle(_signal(OrderSide.BACK, "20", "2.00"), _filled("20", "2.00"))
    realised = settle(_signal(OrderSide.LAY, "10", "1.80"), _filled("10", "1.80"))
    assert realised == Decimal("2.00")
    # Residual BACK 10 @ 2.00 remains. Close with another LAY 10 @ 2.00
    # → realised = 10 * (2.00 - 2.00) = 0: proves entry price is preserved
    # on partial close (not re-averaged against the closing price).
    residual_realised = settle(_signal(OrderSide.LAY, "10", "2.00"), _filled("10", "2.00"))
    assert residual_realised == Decimal("0")


def test_build_delta_pnl_settlement_full_close_then_flip() -> None:
    """An opposite fill larger than the open position closes + flips side."""
    settle = build_delta_pnl_settlement()
    settle(_signal(OrderSide.BACK, "10", "2.00"), _filled("10", "2.00"))
    # LAY 15 @ 1.80 — closes 10 at +0.20 each (+2.00), residual 5 short at 1.80.
    realised = settle(_signal(OrderSide.LAY, "15", "1.80"), _filled("15", "1.80"))
    assert realised == Decimal("2.00")
    # Now close the residual short with BACK 5 @ 1.70: 5 * (1.80 - 1.70) = 0.50.
    closing = settle(_signal(OrderSide.BACK, "5", "1.70"), _filled("5", "1.70"))
    assert closing == Decimal("0.50")


def test_build_delta_pnl_settlement_per_market_isolation() -> None:
    settle = build_delta_pnl_settlement()
    # Open positions on two distinct (venue, market_id) keys.
    settle(
        _signal(OrderSide.BACK, "10", "2.00", market_id="m-A"),
        _filled("10", "2.00"),
    )
    settle(
        _signal(OrderSide.BACK, "10", "3.00", market_id="m-B"),
        _filled("10", "3.00"),
    )
    # A LAY on market m-A must not touch market m-B's position, and vice versa.
    realised_a = settle(
        _signal(OrderSide.LAY, "10", "1.80", market_id="m-A"),
        _filled("10", "1.80"),
    )
    assert realised_a == Decimal("2.00")
    realised_b = settle(
        _signal(OrderSide.LAY, "10", "2.50", market_id="m-B"),
        _filled("10", "2.50"),
    )
    assert realised_b == Decimal("5.00")


def test_build_delta_pnl_settlement_ignores_unfilled() -> None:
    """Unfilled / zero-stake results contribute Decimal('0') unconditionally."""
    settle = build_delta_pnl_settlement()
    unfilled = ExecutionResult(
        order_id="00000000-0000-0000-0000-000000000010",
        strategy_id="strat-001",
        mode="paper",
        status="placed",
        filled_stake=Decimal("0"),
        filled_price=None,
        timestamp=datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
    )
    realised = settle(_signal(OrderSide.BACK, "10", "2.00"), unfilled)
    assert realised == Decimal("0")


def test_build_delta_pnl_settlement_closures_are_independent() -> None:
    """Two closures must not share state — each run starts with a clean book."""
    settle_a = build_delta_pnl_settlement()
    settle_b = build_delta_pnl_settlement()
    settle_a(_signal(OrderSide.BACK, "10", "2.00"), _filled("10", "2.00"))
    # settle_b has never seen this market, so a LAY must open a fresh short,
    # not close settle_a's position.
    realised = settle_b(_signal(OrderSide.LAY, "10", "1.80"), _filled("10", "1.80"))
    assert realised == Decimal("0")


def test_total_pnl_gbp_from_pnls_sums_decimals() -> None:
    assert total_pnl_gbp_from_pnls([]) == Decimal("0")
    assert total_pnl_gbp_from_pnls([Decimal("2.00"), Decimal("-0.50"), Decimal("3.75")]) == Decimal(
        "5.25"
    )


def test_win_rate_from_pnls_counts_only_closes() -> None:
    """Opening / extending fills record Decimal('0'); they must be excluded."""
    # Three closes: two winners, one loser. Zeros (opens) are filtered.
    pnls = [Decimal("0"), Decimal("2"), Decimal("-1"), Decimal("0"), Decimal("3")]
    assert win_rate_from_pnls(pnls) == 2 / 3


def test_win_rate_from_pnls_all_opens_is_zero() -> None:
    assert win_rate_from_pnls([Decimal("0"), Decimal("0")]) == 0.0


def test_win_rate_from_pnls_empty_is_zero() -> None:
    assert win_rate_from_pnls([]) == 0.0

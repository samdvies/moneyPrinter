"""Unit tests for the pure metrics module."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

from algobet_common.schemas import ExecutionResult
from backtest_engine.metrics import (
    max_drawdown_gbp,
    sharpe,
    total_pnl_gbp,
    trivial_settlement,
    win_rate,
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
    fills = [_fill(), _fill(filled_stake="5")]
    assert total_pnl_gbp(fills, trivial_settlement) == Decimal("0")


def test_total_pnl_custom_settlement_sums() -> None:
    fills = [_fill(), _fill(filled_stake="5")]
    result = total_pnl_gbp(fills, lambda _f: Decimal("2.50"))
    assert result == Decimal("5.00")


def test_total_pnl_skips_resting_orders() -> None:
    fills = [_resting(), _fill()]
    result = total_pnl_gbp(fills, lambda _f: Decimal("3"))
    assert result == Decimal("3")


def test_total_pnl_empty_returns_zero() -> None:
    assert total_pnl_gbp([], trivial_settlement) == Decimal("0")


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
    # Trivial settlement returns 0 for every fill, so no fill counts as a win.
    assert win_rate([_fill(), _fill()]) == 0.0

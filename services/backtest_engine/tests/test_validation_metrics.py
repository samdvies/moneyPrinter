"""Tests for validation ``metrics`` module (per-period returns and trades)."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest
from backtest_engine.metrics import (
    compute_all_metrics,
    compute_avg_trade,
    compute_expectancy,
    compute_hit_rate,
    compute_max_drawdown,
    compute_profit_factor,
    compute_sharpe,
    compute_sortino,
    compute_win_rate,
)

# Hand-verified 10-value return series (arithmetic returns, daily-like).
_KNOWN_RETURNS = np.array(
    [0.01, -0.02, 0.015, 0.008, -0.005, 0.012, -0.009, 0.004, 0.006, -0.003],
    dtype=float,
)
_EXPECTED_SHARPE = 2.6235524296395933
_EXPECTED_SORTINO = 3.981705737811908


def test_compute_sharpe_matches_hand_calculation() -> None:
    assert math.isclose(compute_sharpe(_KNOWN_RETURNS), _EXPECTED_SHARPE, rel_tol=0, abs_tol=1e-6)
    assert math.isclose(
        compute_sortino(_KNOWN_RETURNS),
        _EXPECTED_SORTINO,
        rel_tol=0,
        abs_tol=1e-6,
    )


def test_compute_max_drawdown_monotone_decreasing_full_drawdown() -> None:
    eq = np.array([100.0, 90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0])
    m = compute_max_drawdown(eq)
    assert m["peak"] == 100.0
    assert m["trough"] == 10.0
    assert math.isclose(m["depth_pct"], -0.9, rel_tol=0, abs_tol=1e-9)
    assert m["duration_bars"] == 9


def test_compute_max_drawdown_monotone_increasing_zero() -> None:
    eq = np.array([1.0, 2.0, 3.0, 5.0])
    m = compute_max_drawdown(eq)
    assert m["depth_pct"] == 0.0


def test_compute_max_drawdown_v_shape() -> None:
    eq = np.array([100.0, 70.0, 100.0])
    m = compute_max_drawdown(eq)
    assert m["peak"] == 100.0
    assert m["trough"] == 70.0
    assert math.isclose(m["depth_pct"], -0.3, rel_tol=0, abs_tol=1e-9)


def test_hit_rate_win_rate_profit_factor_expectancy() -> None:
    ts = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)
    trades = [
        {"entry_ts": ts, "exit_ts": ts, "pnl": 10.0, "stake": 1.0, "venue": "p", "market_id": "a"},
        {"entry_ts": ts, "exit_ts": ts, "pnl": -5.0, "stake": 1.0, "venue": "p", "market_id": "a"},
        {"entry_ts": ts, "exit_ts": ts, "pnl": 3.0, "stake": 1.0, "venue": "p", "market_id": "a"},
    ]
    assert compute_hit_rate(trades) == 2 / 3
    assert compute_win_rate(trades) == compute_hit_rate(trades)
    assert compute_profit_factor(trades) == 13.0 / 5.0
    assert math.isclose(compute_expectancy(trades), 8.0 / 3.0)
    assert compute_avg_trade(trades) == 1.0


def test_compute_all_metrics_keys() -> None:
    ts = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)
    trades = [
        {"entry_ts": ts, "exit_ts": ts, "pnl": 1.0, "stake": 1.0, "venue": "p", "market_id": "m"},
        {"entry_ts": ts, "exit_ts": ts, "pnl": -1.0, "stake": 1.0, "venue": "p", "market_id": "m"},
    ]
    eq = np.array([100.0, 102.0, 101.0], dtype=float)
    m = compute_all_metrics(trades, eq)
    expected_keys = {
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
        "hit_rate",
        "win_rate",
        "profit_factor",
        "expectancy",
        "avg_trade",
        "n_trades",
    }
    assert set(m.keys()) == expected_keys
    assert m["n_trades"] == 2
    assert isinstance(m["max_drawdown"], dict)


def test_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        compute_sharpe(np.array([]))
    with pytest.raises(ValueError, match="at least 2"):
        compute_sharpe(np.array([1.0]))
    with pytest.raises(ValueError, match="non-empty"):
        compute_max_drawdown(np.array([]))
    with pytest.raises(ValueError, match="non-empty"):
        compute_hit_rate([])


def test_sharpe_all_zero_returns_zero() -> None:
    z = np.zeros(20, dtype=float)
    assert compute_sharpe(z) == 0.0

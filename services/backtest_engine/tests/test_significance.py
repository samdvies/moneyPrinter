"""Tests for deterministic statistical helpers (``significance``)."""

from __future__ import annotations

import numpy as np
from backtest_engine.metrics import compute_sharpe
from backtest_engine.significance import (
    block_bootstrap_ci,
    bootstrap_sharpe_ci,
    compare_to_random_baseline,
    t_test_vs_zero,
)


def test_bootstrap_sharpe_ci_contains_analytical_sharpe() -> None:
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.02, size=80)
    analytical = compute_sharpe(returns, ann_factor=252.0)
    lo, hi = bootstrap_sharpe_ci(returns, n_bootstrap=2000, alpha=0.05, rng=rng)
    assert lo <= analytical <= hi


def test_t_test_normal_zero_not_significant() -> None:
    rng = np.random.default_rng(123)
    sample = rng.normal(0.0, 1.0, size=1000)
    out = t_test_vs_zero(sample)
    assert out["p_value"] > 0.05


def test_t_test_normal_shifted_significant() -> None:
    rng = np.random.default_rng(456)
    sample = rng.normal(0.3, 1.0, size=1000)
    out = t_test_vs_zero(sample)
    assert out["p_value"] < 0.05
    assert out["mean"] > 0.1


def test_block_bootstrap_wider_than_iid_on_ar1() -> None:
    """Block bootstrap CI for Sharpe should be wider than IID bootstrap on AR(1)."""
    rng = np.random.default_rng(7)
    n = 500
    phi = 0.85
    eps = rng.normal(0, 0.01, size=n)
    r = np.zeros(n)
    for t in range(1, n):
        r[t] = phi * r[t - 1] + eps[t]

    rng_iid = np.random.default_rng(100)
    rng_blk = np.random.default_rng(100)
    lo_iid, hi_iid = bootstrap_sharpe_ci(r, n_bootstrap=3000, alpha=0.05, rng=rng_iid)

    def _sharpe_metric(x: np.ndarray) -> float:
        return compute_sharpe(x, ann_factor=252.0)

    lo_blk, hi_blk = block_bootstrap_ci(
        r,
        _sharpe_metric,
        block_size=20,
        n_bootstrap=3000,
        alpha=0.05,
        rng=rng_blk,
    )
    width_iid = hi_iid - lo_iid
    width_blk = hi_blk - lo_blk
    assert width_blk > width_iid


def test_compare_to_random_baseline_no_edge_mostly_non_significant() -> None:
    rng_master = np.random.default_rng(2026)
    non_sig = 0
    runs = 20
    for _ in range(runs):
        rng = np.random.default_rng(rng_master.integers(0, 2**31 - 1))
        p = 200
        prices = np.cumsum(rng.normal(0, 0.02, size=p)) + 100.0
        trades = []
        for j in range(30):
            idx = int(rng.integers(0, p - 2))
            trades.append(
                {
                    "entry_ts": j,
                    "exit_ts": j + 1,
                    "pnl": float(prices[idx + 1] - prices[idx]),
                    "stake": 1.0,
                    "venue": "polymarket",
                    "market_id": "m",
                }
            )
        out = compare_to_random_baseline(
            trades,
            n_simulations=500,
            reference_returns=prices,
            rng=rng,
        )
        if out["p_value_sharpe"] > 0.05 and out["p_value_mean_pnl"] > 0.05:
            non_sig += 1
    assert non_sig >= 17  # at least 85%


def test_t_test_vs_zero_keys() -> None:
    x = np.array([0.1, -0.05, 0.02])
    out = t_test_vs_zero(x)
    for k in ("t_stat", "p_value", "df", "mean", "std_err"):
        assert k in out

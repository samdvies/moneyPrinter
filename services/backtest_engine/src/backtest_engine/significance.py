"""Deterministic statistical inference helpers (bootstrap, t-tests).

All functions accept an optional ``numpy.random.Generator`` for reproducibility.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from scipy import stats

from backtest_engine.metrics import compute_sharpe


def bootstrap_sharpe_ci(
    returns: np.ndarray,
    n_bootstrap: int = 10_000,
    alpha: float = 0.05,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for annualised Sharpe.

    Resamples ``returns`` with replacement ``n_bootstrap`` times, computes
    :func:`backtest_engine.metrics.compute_sharpe` on each sample, and returns
    the ``alpha/2`` and ``1 - alpha/2`` empirical quantiles.
    """
    g = np.random.default_rng(rng) if rng is not None else np.random.default_rng()
    arr = np.asarray(returns, dtype=float)
    if arr.size < 2:
        msg = "returns must have length >= 2"
        raise ValueError(msg)
    stats_list: list[float] = []
    for _ in range(n_bootstrap):
        sample = g.choice(arr, size=arr.size, replace=True)
        stats_list.append(compute_sharpe(sample, ann_factor=252.0))
    dist = np.asarray(stats_list, dtype=float)
    lo = float(np.quantile(dist, alpha / 2))
    hi = float(np.quantile(dist, 1.0 - alpha / 2))
    return lo, hi


def block_bootstrap_ci(
    returns: np.ndarray,
    metric_fn: Callable[[np.ndarray], float],
    block_size: int = 20,
    n_bootstrap: int = 10_000,
    alpha: float = 0.05,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Circular block bootstrap percentile CI for an arbitrary scalar metric.

    Each bootstrap replicate concatenates full blocks drawn uniformly at
    random until length ``>= n``, then truncates to ``n`` to match the
    original series length.
    """
    g = np.random.default_rng(rng) if rng is not None else np.random.default_rng()
    arr = np.asarray(returns, dtype=float)
    n = arr.size
    if n < 1:
        msg = "returns must be non-empty"
        raise ValueError(msg)
    if block_size < 1:
        msg = "block_size must be >= 1"
        raise ValueError(msg)
    extended = np.concatenate([arr, arr[: block_size - 1]])
    vals: list[float] = []
    max_start = n
    for _ in range(n_bootstrap):
        pieces: list[np.ndarray] = []
        while sum(len(p) for p in pieces) < n:
            start = int(g.integers(0, max_start))
            pieces.append(extended[start : start + block_size])
        rep = np.concatenate(pieces)[:n]
        vals.append(float(metric_fn(rep)))
    dist = np.asarray(vals, dtype=float)
    lo = float(np.quantile(dist, alpha / 2))
    hi = float(np.quantile(dist, 1.0 - alpha / 2))
    return lo, hi


def t_test_vs_zero(returns: np.ndarray) -> dict[str, float]:
    """One-sample t-test of the mean return against zero.

    Returns keys ``t_stat``, ``p_value``, ``df``, ``mean``, ``std_err``.
    """
    arr = np.asarray(returns, dtype=float)
    if arr.size < 2:
        msg = "returns must have length >= 2"
        raise ValueError(msg)
    res = stats.ttest_1samp(arr, 0.0, alternative="two-sided")
    mean = float(arr.mean())
    std_err = float(arr.std(ddof=1) / np.sqrt(arr.size))
    df_val = float(res.df) if getattr(res, "df", None) is not None else float(arr.size - 1)
    return {
        "t_stat": float(res.statistic),
        "p_value": float(res.pvalue),
        "df": df_val,
        "mean": mean,
        "std_err": std_err,
    }


def compare_to_random_baseline(
    strategy_trades: list[dict[str, Any]],
    n_simulations: int = 1_000,
    reference_returns: np.ndarray | None = None,
    rng: np.random.Generator | None = None,
) -> dict[str, float]:
    """Compare strategy trade P&Ls to a null of random entries on the same path.

    If ``reference_returns`` is a 1-D **price** (or level) series, each
    simulation draws ``len(strategy_trades)`` random start indices ``i`` and
    assigns ``pnl_i = level[i+1] - level[i]`` (one-bar hold, random entry time).

    If ``reference_returns`` is ``None``, the null permutes the observed trade
    P&Ls (same multiset, random order).

    Returns ``p_value_sharpe``, ``p_value_mean_pnl``, ``sharpe_percentile``,
    ``mean_pnl_percentile`` using simple one-sided empirical ranks:
    ``(1 + #{null >= actual}) / (n_simulations + 1)``.
    """
    g = np.random.default_rng(rng) if rng is not None else np.random.default_rng()
    if not strategy_trades:
        msg = "strategy_trades must be non-empty"
        raise ValueError(msg)
    pnls = np.array([float(t["pnl"]) for t in strategy_trades], dtype=float)
    n = pnls.size
    if n < 2:
        msg = "need at least 2 trades for Sharpe comparison"
        raise ValueError(msg)

    actual_mean = float(pnls.mean())
    actual_sharpe = compute_sharpe(pnls, ann_factor=252.0)

    sim_means = np.empty(n_simulations, dtype=float)
    sim_sharpes = np.empty(n_simulations, dtype=float)

    if reference_returns is not None:
        level = np.asarray(reference_returns, dtype=float)
        if level.size < n + 1:
            msg = "reference_returns (price path) must have length > n_trades"
            raise ValueError(msg)
        max_i = level.size - 2
        for s in range(n_simulations):
            idx = g.integers(0, max_i + 1, size=n)
            sim_pnls = level[idx + 1] - level[idx]
            sim_means[s] = float(sim_pnls.mean())
            sim_sharpes[s] = compute_sharpe(sim_pnls, ann_factor=252.0)
    else:
        for s in range(n_simulations):
            perm = g.permutation(pnls)
            sim_means[s] = float(perm.mean())
            sim_sharpes[s] = compute_sharpe(perm, ann_factor=252.0)

    p_mean = float((1 + np.sum(sim_means >= actual_mean)) / (n_simulations + 1))
    p_sharpe = float((1 + np.sum(sim_sharpes >= actual_sharpe)) / (n_simulations + 1))
    sharpe_pct = float(np.mean(sim_sharpes <= actual_sharpe))
    mean_pct = float(np.mean(sim_means <= actual_mean))

    return {
        "p_value_sharpe": p_sharpe,
        "p_value_mean_pnl": p_mean,
        "sharpe_percentile": sharpe_pct,
        "mean_pnl_percentile": mean_pct,
    }

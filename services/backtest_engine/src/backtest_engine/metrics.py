"""Validation metrics on per-period returns and completed trades.

Pure functions: no logging, no I/O, no hidden randomness. Returns are
assumed to be **arithmetic** simple returns (not log returns). Sharpe /
Sortino use sample standard deviation with ``ddof=1`` when ``n >= 2``.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

import numpy as np

__all__ = [
    "compute_all_metrics",
    "compute_avg_trade",
    "compute_calmar",
    "compute_expectancy",
    "compute_hit_rate",
    "compute_max_drawdown",
    "compute_profit_factor",
    "compute_sharpe",
    "compute_sortino",
    "compute_win_rate",
]


def _to_float(x: Decimal | float) -> float:
    if isinstance(x, Decimal):
        return float(x)
    return float(x)


def compute_sharpe(returns: np.ndarray, ann_factor: float = 252.0) -> float:
    """Annualised Sharpe: mean / std * sqrt(ann_factor).

    Empty or length-1 ``returns`` raises ``ValueError``. All-zero sample
    variance returns ``0.0`` (avoids NaN in downstream JSON).
    """
    arr = np.asarray(returns, dtype=float)
    if arr.size < 2:
        msg = "returns must have at least 2 samples for Sharpe"
        raise ValueError(msg)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1))
    if std <= 0.0 or not math.isfinite(std):
        return 0.0
    return (mean / std) * math.sqrt(ann_factor)


def compute_sortino(
    returns: np.ndarray,
    ann_factor: float = 252.0,
    mar: float = 0.0,
) -> float:
    """Sortino using downside deviation vs ``mar``.

    Downside deviation is ``sqrt(mean((min(r - mar, 0))^2))`` over **all**
    observations (zeros contribute). Empty or length-1 raises
    ``ValueError``. If every return is ``>= mar`` (no downside), returns
    ``0.0``.
    """
    arr = np.asarray(returns, dtype=float)
    if arr.size < 2:
        msg = "returns must have at least 2 samples for Sortino"
        raise ValueError(msg)
    mean = float(arr.mean())
    downside = np.minimum(arr - mar, 0.0)
    if not np.any(downside < 0):
        return 0.0
    dsd = float(np.sqrt(np.mean(downside**2)))
    if dsd <= 0.0 or not math.isfinite(dsd):
        return 0.0
    return ((mean - mar) / dsd) * math.sqrt(ann_factor)


def compute_max_drawdown(equity_curve: np.ndarray) -> dict[str, Any]:
    """Peak-to-trough drawdown on an equity **level** series.

    Returns dict with ``peak`` and ``trough`` at the worst drawdown episode,
    ``depth_pct`` (negative fraction of the peak at that episode, e.g. ``-0.25``
    for a 25% drawdown), and ``duration_bars`` (trough index minus peak index).

    Empty curve raises ``ValueError``.
    """
    eq = np.asarray(equity_curve, dtype=float)
    if eq.size == 0:
        msg = "equity_curve must be non-empty"
        raise ValueError(msg)
    running_peak = float(eq[0])
    peak_i = 0
    worst_depth = 0.0
    worst_peak = running_peak
    worst_trough = running_peak
    worst_duration = 0
    for i in range(1, eq.size):
        v = float(eq[i])
        if v > running_peak:
            running_peak = v
            peak_i = i
        if running_peak != 0.0:
            dd_pct = (v - running_peak) / running_peak
        elif v == 0.0:
            dd_pct = 0.0
        else:
            dd_pct = float("-inf")
        if dd_pct < worst_depth:
            worst_depth = dd_pct
            worst_peak = running_peak
            worst_trough = v
            worst_duration = i - peak_i
    return {
        "peak": float(worst_peak),
        "trough": float(worst_trough),
        "depth_pct": float(worst_depth),
        "duration_bars": int(worst_duration),
    }


def compute_calmar(
    returns: np.ndarray,
    equity_curve: np.ndarray,
    ann_factor: float = 252.0,
) -> float:
    """Annualised return / abs(max drawdown depth as positive fraction).

    Uses arithmetic mean return * ann_factor as annual return proxy.
    If max drawdown depth is zero, returns ``0.0``.
    """
    arr = np.asarray(returns, dtype=float)
    eq = np.asarray(equity_curve, dtype=float)
    if arr.size == 0 or eq.size == 0:
        msg = "returns and equity_curve must be non-empty"
        raise ValueError(msg)
    mdd = compute_max_drawdown(eq)
    depth = abs(mdd["depth_pct"]) if mdd["depth_pct"] < 0 else 0.0
    ann_ret = float(arr.mean()) * ann_factor
    if depth <= 0.0:
        return 0.0
    return ann_ret / depth


def compute_hit_rate(trades: list[dict[str, Any]]) -> float:
    """Fraction of trades with ``pnl > 0``."""
    if not trades:
        msg = "trades must be non-empty"
        raise ValueError(msg)
    wins = sum(1 for t in trades if _to_float(t["pnl"]) > 0.0)
    return wins / len(trades)


def compute_win_rate(trades: list[dict[str, Any]]) -> float:
    """Alias of :func:`compute_hit_rate`."""
    return compute_hit_rate(trades)


def compute_profit_factor(trades: list[dict[str, Any]]) -> float:
    """Sum of winning ``pnl`` / abs(sum of losing ``pnl``).

    No losses or zero loss sum returns ``0.0``.
    """
    if not trades:
        msg = "trades must be non-empty"
        raise ValueError(msg)
    gross_win = sum(_to_float(t["pnl"]) for t in trades if _to_float(t["pnl"]) > 0.0)
    gross_loss = sum(_to_float(t["pnl"]) for t in trades if _to_float(t["pnl"]) < 0.0)
    if gross_loss == 0.0:
        return 0.0
    return gross_win / abs(gross_loss)


def compute_expectancy(trades: list[dict[str, Any]]) -> float:
    """Average ``pnl`` per trade."""
    if not trades:
        msg = "trades must be non-empty"
        raise ValueError(msg)
    return sum(_to_float(t["pnl"]) for t in trades) / len(trades)


def compute_avg_trade(trades: list[dict[str, Any]]) -> float:
    """Average absolute ``stake`` per trade (exposure proxy)."""
    if not trades:
        msg = "trades must be non-empty"
        raise ValueError(msg)
    return sum(abs(_to_float(t["stake"])) for t in trades) / len(trades)


def compute_all_metrics(
    trades: list[dict[str, Any]],
    equity_curve: np.ndarray,
    ann_factor: float = 252.0,
) -> dict[str, Any]:
    """Aggregate trade and equity-curve metrics (snake_case keys)."""
    if not trades:
        msg = "trades must be non-empty"
        raise ValueError(msg)
    eq = np.asarray(equity_curve, dtype=float)
    if eq.size < 2:
        msg = "equity_curve must have at least 2 points to derive returns"
        raise ValueError(msg)
    rets = np.diff(eq) / np.where(eq[:-1] != 0.0, eq[:-1], 1.0)
    mdd = compute_max_drawdown(eq)
    out: dict[str, Any] = {
        "sharpe": compute_sharpe(rets, ann_factor=ann_factor),
        "sortino": compute_sortino(rets, ann_factor=ann_factor),
        "max_drawdown": mdd,
        "calmar": compute_calmar(rets, eq, ann_factor=ann_factor),
        "hit_rate": compute_hit_rate(trades),
        "win_rate": compute_win_rate(trades),
        "profit_factor": compute_profit_factor(trades),
        "expectancy": compute_expectancy(trades),
        "avg_trade": compute_avg_trade(trades),
        "n_trades": len(trades),
    }
    return out

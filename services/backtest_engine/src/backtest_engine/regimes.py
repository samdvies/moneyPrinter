"""Simple regime labelling for conditional metrics."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd


def label_vol_regime(
    prices: pd.Series,
    window: int = 30,
    quantile_high: float = 0.75,
) -> pd.Series:
    """Rolling std percentile; labels ``high`` / ``low`` aligned to ``prices``."""
    if window < 2:
        msg = "window must be >= 2"
        raise ValueError(msg)
    roll_std = prices.rolling(window=window, min_periods=window).std()
    q = roll_std.quantile(quantile_high)
    out = pd.Series(index=prices.index, dtype=object)
    mask_valid = roll_std.notna()
    out.loc[mask_valid & (roll_std >= q)] = "high"
    out.loc[mask_valid & (roll_std < q)] = "low"
    return out


def label_trend_regime(
    prices: pd.Series,
    window: int = 30,
    slope_threshold: float = 0.001,
) -> pd.Series:
    """Rolling OLS slope on index positions; ``up`` / ``down`` / ``flat``."""
    if window < 2:
        msg = "window must be >= 2"
        raise ValueError(msg)
    out = pd.Series(index=prices.index, dtype=object)
    y_all = prices.astype(float).values
    x = np.arange(len(prices), dtype=float)
    for i in range(len(prices)):
        if i + 1 < window:
            continue
        sl = slice(i + 1 - window, i + 1)
        xs = x[sl]
        ys = y_all[sl]
        x_mean = xs.mean()
        denom = np.sum((xs - x_mean) ** 2)
        if denom <= 0:
            out.iloc[i] = "flat"
            continue
        slope = float(np.sum((xs - x_mean) * (ys - ys.mean())) / denom)
        if slope > slope_threshold:
            out.iloc[i] = "up"
        elif slope < -slope_threshold:
            out.iloc[i] = "down"
        else:
            out.iloc[i] = "flat"
    return out


def regime_conditional_metrics(
    trades: list[dict[str, Any]],
    regimes: pd.Series,
    metric_fn: Callable[[list[dict[str, Any]]], float],
) -> dict[str, float]:
    """Apply ``metric_fn`` to trades grouped by regime at ``entry_ts``."""
    by_regime: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        ts = t["entry_ts"]
        key_ts = ts.replace(tzinfo=None) if getattr(ts, "tzinfo", None) is not None else ts
        if key_ts not in regimes.index:
            continue
        label = regimes.loc[key_ts]
        if not isinstance(label, str) or pd.isna(label):
            continue
        by_regime.setdefault(label, []).append(t)
    return {f"{k}_metric": float(metric_fn(v)) for k, v in by_regime.items()}

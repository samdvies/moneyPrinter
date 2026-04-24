"""Parameter grid search over tick replay."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from itertools import product
from typing import Any

import pandas as pd
from algobet_common.schemas import MarketData, OrderSignal

from backtest_engine.walkforward import run_strategy_metrics


def param_grid(param_ranges: dict[str, list[Any]]) -> Iterator[dict[str, Any]]:
    """Cartesian product of parameter lists (keys preserved)."""
    if not param_ranges:
        yield {}
        return
    keys = list(param_ranges.keys())
    for combo in product(*[param_ranges[k] for k in keys]):
        yield dict(zip(keys, combo, strict=True))


def run_sweep(
    strategy_on_tick: Callable[
        [MarketData, dict[str, Any], datetime],
        OrderSignal | None,
    ],
    ticks: list[MarketData],
    grid: Iterator[dict[str, Any]],
    metric: str = "sharpe",
) -> pd.DataFrame:
    """One row per grid point: param columns plus all replay metrics."""
    rows: list[dict[str, Any]] = []
    for p in grid:
        m = run_strategy_metrics(strategy_on_tick, ticks, p)
        row = {**p, **m}
        rows.append(row)
    df = pd.DataFrame(rows)
    if rows and metric not in df.columns:
        msg = f"metric {metric!r} not produced by replay"
        raise ValueError(msg)
    return df


def stability_score(df: pd.DataFrame, metric: str = "sharpe", top_k: int = 5) -> float:
    """std/mean of ``metric`` over the top_k rows by ``metric``; lower is stabler."""
    if df.empty or metric not in df.columns:
        return 0.0
    sub = df.nlargest(min(top_k, len(df)), metric)
    vals = sub[metric].astype(float)
    mean = float(vals.mean())
    if abs(mean) < 1e-12:
        return float("inf") if float(vals.std(ddof=1)) > 1e-12 else 0.0
    std = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    return std / abs(mean)

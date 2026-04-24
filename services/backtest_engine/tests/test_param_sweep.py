"""Tests for parameter sweep helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
from algobet_common.schemas import MarketData, Venue
from backtest_engine.param_sweep import param_grid, run_sweep, stability_score
from backtest_engine.strategies import mean_reversion


def test_param_grid_cartesian() -> None:
    combos = list(param_grid({"a": [1, 2], "b": [3, 4]}))
    assert len(combos) == 4
    keys = {tuple(sorted(d.items())) for d in combos}
    assert keys == {
        (("a", 1), ("b", 3)),
        (("a", 1), ("b", 4)),
        (("a", 2), ("b", 3)),
        (("a", 2), ("b", 4)),
    }


def _ticks(n: int = 80) -> list[MarketData]:
    base = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)
    out: list[MarketData] = []
    for i in range(n):
        mid = Decimal("0.5") + Decimal(str(0.002 * np.sin(i / 4.0)))
        sp = Decimal("0.01")
        out.append(
            MarketData(
                venue=Venue.POLYMARKET,
                market_id="m",
                timestamp=base.replace(microsecond=i),
                bids=[(mid - sp / 2, Decimal("10"))],
                asks=[(mid + sp / 2, Decimal("10"))],
            )
        )
    return out


def test_run_sweep_nine_rows() -> None:
    ticks = _ticks()
    grid = param_grid(
        {
            "window_size": [8, 10, 12],
            "z_threshold": [1.0, 1.2, 1.4],
            "stake_gbp": ["1.0"],
            "min_stddev": [0.0001],
            "venue": ["polymarket"],
        }
    )
    df = run_sweep(mean_reversion.on_tick, ticks, grid, metric="sharpe")
    assert len(df) == 9
    assert "sharpe" in df.columns
    assert "window_size" in df.columns


def test_stability_score_spiky() -> None:
    df = pd.DataFrame({"sharpe": [10.0, 9.5, -2.0, 8.0, 0.1, -5.0]})
    assert stability_score(df, metric="sharpe", top_k=5) > 0.5


def test_stability_score_flat() -> None:
    df = pd.DataFrame({"sharpe": [1.01, 1.02, 0.99, 1.0, 1.01]})
    assert stability_score(df, metric="sharpe", top_k=5) < 0.2

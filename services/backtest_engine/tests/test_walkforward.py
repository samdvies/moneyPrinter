"""Tests for walk-forward split generation and aggregation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest
from algobet_common.schemas import MarketData, Venue
from backtest_engine.strategies import mean_reversion
from backtest_engine.walkforward import (
    WalkForwardSplit,
    generate_splits,
    summarise_walkforward,
    walkforward_run,
)


def test_generate_splits_count_and_indices() -> None:
    n_bars = 100
    train_bars = 40
    test_bars = 10
    step = test_bars
    splits = generate_splits(n_bars, train_bars, test_bars, step=step)
    expected_n = (n_bars - train_bars) // step
    assert len(splits) == expected_n
    assert splits[0].train_start == 0
    assert splits[0].train_end == train_bars
    assert splits[0].test_start == train_bars
    assert splits[0].test_end == train_bars + test_bars
    last = splits[-1]
    assert last.test_end <= n_bars


def test_walkforward_run_returns_is_oos_keys() -> None:
    base = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)
    ticks: list[MarketData] = []
    for i in range(120):
        mid = Decimal("0.5") + Decimal(str(0.001 * np.sin(i / 3.0)))
        spread = Decimal("0.01")
        ticks.append(
            MarketData(
                venue=Venue.POLYMARKET,
                market_id="m1",
                timestamp=base.replace(second=i % 60, microsecond=i),
                bids=[(mid - spread / 2, Decimal("10"))],
                asks=[(mid + spread / 2, Decimal("10"))],
            )
        )
    params = {
        "window_size": 15,
        "z_threshold": 1.5,
        "stake_gbp": "1.0",
        "min_stddev": 0.0001,
        "venue": "polymarket",
    }
    split = WalkForwardSplit(train_start=0, train_end=60, test_start=60, test_end=120)
    result = walkforward_run(mean_reversion.on_tick, ticks, split, params, fit_fn=None)
    assert "in_sample" in result and "out_of_sample" in result
    assert result["split"] == split
    assert "sharpe" in result["in_sample"]


def test_summarise_walkforward_degradation_ratio() -> None:
    results = [
        {
            "in_sample": {"sharpe": 2.0},
            "out_of_sample": {"sharpe": 0.5},
            "split": WalkForwardSplit(0, 10, 10, 20),
        },
        {
            "in_sample": {"sharpe": 1.0},
            "out_of_sample": {"sharpe": 0.25},
            "split": WalkForwardSplit(0, 10, 10, 20),
        },
    ]
    s = summarise_walkforward(results)
    assert s["mean_is_sharpe"] == 1.5
    assert s["mean_oos_sharpe"] == 0.375
    assert pytest.approx(s["degradation_ratio"]) == 0.375 / 1.5

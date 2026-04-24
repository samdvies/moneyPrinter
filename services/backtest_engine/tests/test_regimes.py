"""Tests for regime labelling."""

from __future__ import annotations

import numpy as np
import pandas as pd
from backtest_engine.metrics import compute_expectancy
from backtest_engine.regimes import (
    label_trend_regime,
    label_vol_regime,
    regime_conditional_metrics,
)


def test_label_vol_regime_high_in_volatile_slice() -> None:
    rng = np.random.default_rng(0)
    idx = pd.RangeIndex(0, 120)
    calm = np.full(60, 100.0)
    noisy = 100.0 + rng.normal(0, 2.0, size=60)
    s = pd.Series(np.concatenate([calm, noisy]), index=idx)
    reg = label_vol_regime(s, window=20, quantile_high=0.75)
    tail = reg.iloc[85:].dropna()
    assert (tail == "high").any()


def test_label_trend_regime_rising_returns_up() -> None:
    idx = pd.RangeIndex(0, 80)
    rising = pd.Series([float(i) * 0.1 for i in range(80)], index=idx)
    reg = label_trend_regime(rising, window=25, slope_threshold=0.001)
    tail = reg.iloc[50:].dropna()
    assert (tail == "up").all()


def test_regime_conditional_metrics_sums() -> None:
    regimes = pd.Series(["low", "low", "high", "high"], index=[0, 1, 2, 3])
    trades = [
        {"entry_ts": 0, "exit_ts": 1, "pnl": 1.0, "stake": 1.0, "venue": "p", "market_id": "m"},
        {"entry_ts": 1, "exit_ts": 2, "pnl": 2.0, "stake": 1.0, "venue": "p", "market_id": "m"},
        {"entry_ts": 2, "exit_ts": 3, "pnl": -1.0, "stake": 1.0, "venue": "p", "market_id": "m"},
        {"entry_ts": 3, "exit_ts": 4, "pnl": 3.0, "stake": 1.0, "venue": "p", "market_id": "m"},
    ]
    out = regime_conditional_metrics(trades, regimes, compute_expectancy)
    assert "low_metric" in out and "high_metric" in out
    assert out["low_metric"] == 1.5  # (1+2)/2
    assert out["high_metric"] == 1.0  # (-1+3)/2

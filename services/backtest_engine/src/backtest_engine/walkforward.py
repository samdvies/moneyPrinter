"""Rolling walk-forward evaluation on tick lists."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from algobet_common.schemas import ExecutionResult, MarketData, OrderSignal
from simulator.book import Book
from simulator.fills import match_order

from backtest_engine.harness_metrics import (
    build_delta_pnl_settlement,
    max_drawdown_gbp,
    sharpe,
    total_pnl_gbp_from_pnls,
    win_rate_from_pnls,
)


@dataclass(frozen=True)
class WalkForwardSplit:
    """Bar indices into a tick list (``end`` indices are exclusive, slice-like)."""

    train_start: int
    train_end: int
    test_start: int
    test_end: int


def generate_splits(
    n_bars: int,
    train_bars: int,
    test_bars: int,
    step: int | None = None,
) -> list[WalkForwardSplit]:
    """Rolling walk-forward windows; ``step`` defaults to ``test_bars``."""
    if step is None:
        step = test_bars
    if step < 1:
        msg = "step must be >= 1"
        raise ValueError(msg)
    if train_bars < 1 or test_bars < 1:
        msg = "train_bars and test_bars must be >= 1"
        raise ValueError(msg)
    n_splits = (n_bars - train_bars) // step
    out: list[WalkForwardSplit] = []
    for k in range(n_splits):
        ts = k * step
        te = ts + train_bars
        vs = te
        ve = vs + test_bars
        if ve > n_bars:
            break
        out.append(WalkForwardSplit(train_start=ts, train_end=te, test_start=vs, test_end=ve))
    return out


def _replay_ticks(
    strategy_on_tick: Callable[[MarketData, dict[str, Any], datetime], OrderSignal | None],
    ticks: list[MarketData],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic synchronous replay (mirrors harness fill/settlement path)."""
    p = copy.deepcopy(params)
    p.pop("_window", None)

    book = Book()
    fill_log: list[tuple[ExecutionResult, Decimal]] = []
    per_tick_pnl: list[Decimal] = []
    equity_curve: list[Decimal] = []
    running = Decimal("0")
    settlement = build_delta_pnl_settlement()

    for tick in ticks:
        book.update(tick)
        ts = tick.timestamp
        signal = strategy_on_tick(tick, p, ts)
        tick_pnl = Decimal("0")
        if signal is not None:

            def _tick_clock(tick_ts: datetime = ts) -> datetime:
                return tick_ts

            result = match_order(signal, tick, now_fn=_tick_clock)
            realised = settlement(signal, result)
            fill_log.append((result, realised))
            tick_pnl = realised
        running += tick_pnl
        per_tick_pnl.append(tick_pnl)
        equity_curve.append(running)

    realised_pnls = [pnl for _r, pnl in fill_log]
    return {
        "sharpe": sharpe(per_tick_pnl),
        "total_pnl_gbp": total_pnl_gbp_from_pnls(realised_pnls),
        "max_drawdown_gbp": max_drawdown_gbp(equity_curve),
        "n_trades": sum(1 for result, _pnl in fill_log if result.filled_stake > Decimal("0")),
        "win_rate": win_rate_from_pnls(realised_pnls),
        "n_ticks_consumed": len(ticks),
    }


def walkforward_run(
    strategy_on_tick: Callable[[MarketData, dict[str, Any], datetime], OrderSignal | None],
    ticks: list[MarketData],
    split_cfg: WalkForwardSplit,
    params: dict[str, Any],
    fit_fn: Callable[[list[MarketData], dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run in-sample then out-of-sample with optional refit between phases."""
    train_ticks = ticks[split_cfg.train_start : split_cfg.train_end]
    test_ticks = ticks[split_cfg.test_start : split_cfg.test_end]
    is_metrics = _replay_ticks(strategy_on_tick, train_ticks, params)
    oos_params = params
    if fit_fn is not None:
        oos_params = fit_fn(train_ticks, copy.deepcopy(params))
    oos_metrics = _replay_ticks(strategy_on_tick, test_ticks, oos_params)
    return {
        "in_sample": is_metrics,
        "out_of_sample": oos_metrics,
        "split": split_cfg,
    }


def summarise_walkforward(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate IS vs OOS Sharpe and degradation across splits."""
    if not results:
        return {
            "mean_is_sharpe": 0.0,
            "mean_oos_sharpe": 0.0,
            "degradation_ratio": 0.0,
            "oos_win_consistency": 0.0,
            "n_splits": 0,
        }
    is_vals = [float(r["in_sample"]["sharpe"]) for r in results]
    oos_vals = [float(r["out_of_sample"]["sharpe"]) for r in results]
    mean_is = sum(is_vals) / len(is_vals)
    mean_oos = sum(oos_vals) / len(oos_vals)
    if mean_is != 0.0:
        degradation = mean_oos / mean_is
    elif mean_oos == 0.0:
        degradation = 0.0
    else:
        degradation = float("inf")
    wins = sum(1 for v in oos_vals if v > 0.0)
    return {
        "mean_is_sharpe": mean_is,
        "mean_oos_sharpe": mean_oos,
        "degradation_ratio": degradation,
        "oos_win_consistency": wins / len(oos_vals),
        "n_splits": len(results),
    }

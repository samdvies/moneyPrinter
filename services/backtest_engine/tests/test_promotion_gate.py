"""Tests for promotion gate."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backtest_engine.promotion_gate import check_promotion_criteria, load_thresholds
from backtest_engine.validate import BacktestReport


def _report(**kwargs: Any) -> BacktestReport:
    defaults: dict[str, Any] = {
        "strategy_slug": "test-strat",
        "run_id": "00000000-0000-0000-0000-000000000001",
        "run_ts": datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC),
        "data_source": "synthetic",
        "n_trades": 10,
        "metrics": {
            "sharpe": 1.0,
            "hit_rate": 0.5,
            "max_drawdown": {"depth_pct": -0.1},
        },
        "significance": {"random_baseline": {"p_value_sharpe": 0.01}},
        "walkforward": {"degradation_ratio": 0.8},
        "param_sweep_path": None,
        "regime_metrics": {},
        "promotion_pass": True,
        "failure_reasons": [],
    }
    defaults.update(kwargs)
    return BacktestReport(**defaults)


def test_passing_report() -> None:
    th = {
        "sharpe": 0.5,
        "max_dd_pct": -20.0,
        "hit_rate": 0.45,
        "p_value_sharpe": 0.05,
        "walkforward_degradation": 0.5,
    }
    ok, reasons = check_promotion_criteria(_report(), th)
    assert ok and reasons == []


def test_failing_sharpe() -> None:
    th = {
        "sharpe": 0.5,
        "max_dd_pct": -20.0,
        "hit_rate": 0.45,
        "p_value_sharpe": 0.05,
        "walkforward_degradation": 0.5,
    }
    r = _report(metrics={"sharpe": 0.1, "hit_rate": 0.5, "max_drawdown": {"depth_pct": -0.1}})
    ok, reasons = check_promotion_criteria(r, th)
    assert not ok
    assert any("sharpe" in x.lower() for x in reasons)


def test_failing_multiple() -> None:
    th = {
        "sharpe": 0.5,
        "max_dd_pct": -20.0,
        "hit_rate": 0.45,
        "p_value_sharpe": 0.05,
        "walkforward_degradation": 0.5,
    }
    r = _report(
        metrics={"sharpe": 0.1, "hit_rate": 0.1, "max_drawdown": {"depth_pct": -0.99}},
        significance={"random_baseline": {"p_value_sharpe": 0.9}},
        walkforward={"degradation_ratio": 0.1},
    )
    ok, reasons = check_promotion_criteria(r, th)
    assert not ok
    assert len(reasons) >= 2


def test_load_thresholds_from_fixture_wiki(tmp_path: Path) -> None:
    wiki = tmp_path / "my-strategy.md"
    wiki.write_text(
        "---\ntitle: x\ntype: strategy\npromotion_thresholds:\n  sharpe: 0.9\n---\n\nbody\n",
        encoding="utf-8",
    )
    th = load_thresholds("my-strategy", wiki_root=tmp_path)
    assert th["sharpe"] == 0.9
    assert th["hit_rate"] == 0.45  # default preserved for missing keys

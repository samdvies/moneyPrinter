"""Harness-level tests.

The determinism pin is the headline done-when: two consecutive
``run_backtest`` calls against the same source must produce structurally
equal ``BacktestResult`` dicts. Without the ``now_fn`` factoring on
``match_order`` this test would fail on the ``ExecutionResult.timestamp``
captured in metrics (timestamps don't surface in BacktestResult directly,
but the no-wall-clock guarantee still needs proving).
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from algobet_common.schemas import MarketData, Venue
from backtest_engine.harness import run_backtest
from backtest_engine.sources.synthetic import SyntheticSource
from backtest_engine.strategy_protocol import StrategyModule


def _load_fixture_strategy() -> StrategyModule:
    """Load the ``always_back_below_two`` fixture as a module object.

    Uses importlib directly rather than ``import``-statement discovery so
    mypy and ruff do not have to reason about the directory layout of a
    test-only fixture. The harness StrategyModule Protocol is structural,
    so a module object with ``on_tick`` satisfies it at runtime; we cast
    the result here so mypy can keep its type narrowing.
    """
    fixture_path = Path(__file__).parent / "fixtures" / "always_back_below_two.py"
    spec = importlib.util.spec_from_file_location("always_back_below_two", fixture_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["always_back_below_two"] = module
    spec.loader.exec_module(module)
    return cast(StrategyModule, module)


always_back_below_two = _load_fixture_strategy()


def _tick(offset_seconds: int, best_ask: str = "1.40") -> MarketData:
    return MarketData(
        venue=Venue.BETFAIR,
        market_id="test.001",
        timestamp=datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds),
        bids=[(Decimal("1.30"), Decimal("100"))],
        asks=[(Decimal(best_ask), Decimal("100"))],
    )


def _time_range() -> tuple[datetime, datetime]:
    start = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    end = start + timedelta(seconds=120)
    return start, end


async def test_harness_runs_trivial_strategy_and_records_trades() -> None:
    ticks = [_tick(i, best_ask="1.40") for i in range(100)]
    source = SyntheticSource(ticks)
    result = await run_backtest(
        strategy=always_back_below_two,
        params={"stake": Decimal("10")},
        source=source,
        time_range=_time_range(),
    )
    assert result["n_trades"] > 0
    assert result["n_ticks_consumed"] == 100
    # Trivial settlement => zero P&L for every matched order.
    assert result["total_pnl_gbp"] == Decimal("0")
    assert result["max_drawdown_gbp"] == Decimal("0")
    assert result["win_rate"] == 0.0


async def test_harness_skips_when_ask_above_threshold() -> None:
    # Best ask 1.60 > threshold 1.50 => strategy emits no signals.
    ticks = [_tick(i, best_ask="1.60") for i in range(10)]
    source = SyntheticSource(ticks)
    result = await run_backtest(
        strategy=always_back_below_two,
        params={},
        source=source,
        time_range=_time_range(),
    )
    assert result["n_trades"] == 0
    assert result["n_ticks_consumed"] == 10


def _scrub_wallclock(result: dict[str, object]) -> dict[str, object]:
    """Strip wall-clock started_at/ended_at before comparing determinism.

    These come from ``datetime.now(UTC)`` inside the harness and are
    definitionally non-deterministic; the contract guarantees every other
    key is bit-identical across replays.
    """
    return {k: v for k, v in result.items() if k not in {"started_at", "ended_at"}}


async def test_harness_determinism_two_runs_same_source() -> None:
    ticks = [_tick(i, best_ask="1.40") for i in range(100)]
    source = SyntheticSource(ticks)

    first = await run_backtest(
        strategy=always_back_below_two,
        params={"stake": Decimal("10")},
        source=source,
        time_range=_time_range(),
    )
    second = await run_backtest(
        strategy=always_back_below_two,
        params={"stake": Decimal("10")},
        source=source,
        time_range=_time_range(),
    )

    assert _scrub_wallclock(dict(first)) == _scrub_wallclock(dict(second))
    # Sanity: the run actually did something.
    assert first["n_trades"] > 0


async def test_harness_result_shape_matches_contract() -> None:
    ticks = [_tick(0)]
    source = SyntheticSource(ticks)
    result = await run_backtest(
        strategy=always_back_below_two,
        params={},
        source=source,
        time_range=_time_range(),
    )
    expected_keys = {
        "sharpe",
        "total_pnl_gbp",
        "max_drawdown_gbp",
        "n_trades",
        "win_rate",
        "n_ticks_consumed",
        "started_at",
        "ended_at",
    }
    assert set(result.keys()) == expected_keys
    assert isinstance(result["sharpe"], float)
    assert isinstance(result["total_pnl_gbp"], Decimal)
    assert isinstance(result["max_drawdown_gbp"], Decimal)
    assert isinstance(result["n_trades"], int)
    assert isinstance(result["win_rate"], float)
    assert isinstance(result["n_ticks_consumed"], int)
    assert isinstance(result["started_at"], datetime)
    assert isinstance(result["ended_at"], datetime)

"""Harness-level tests.

The determinism pin is the headline done-when: two consecutive
``run_backtest`` calls against the same source must produce structurally
equal ``BacktestResult`` dicts. With the ``clock`` kwarg factored on
``run_backtest`` and the ``now_fn`` factoring on ``match_order``, the
pin asserts bit-identical equality on every key — no wall-clock scrub.

Fixture import strategy:
    See ``tests/conftest.py`` — the service's ``tests/`` directory is
    prepended to ``sys.path`` so ``fixtures`` is importable as a
    top-level package. This avoids a relative import against the shared
    ``tests`` package name, which collides across services under
    ``--import-mode=importlib``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from algobet_common.schemas import MarketData, Venue
from backtest_engine.harness import run_backtest
from backtest_engine.sources.synthetic import SyntheticSource
from backtest_engine.strategy_protocol import StrategyModule

# The ``fixtures`` top-level name is injected by ``tests/conftest.py``
# at collection time via a sys.path prepend. See mypy.ini for the
# corresponding ``[mypy-fixtures.*]`` override that keeps project-wide
# mypy quiet about the conftest-only resolution path.
from fixtures import always_back_below_two as _fixture_module

# The harness StrategyModule Protocol is structural: a module object with
# an ``on_tick`` attribute satisfies it. Casting here keeps mypy's type
# narrowing on ``run_backtest`` without changing runtime behaviour.
always_back_below_two = cast(StrategyModule, _fixture_module)


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


def _fixed_clock() -> datetime:
    """Return a fixed UTC timestamp so ``started_at`` / ``ended_at`` are
    deterministic across replays. Any constant works — the pin just
    requires two runs to agree."""
    return datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)


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


async def test_harness_determinism_two_runs_same_source() -> None:
    ticks = [_tick(i, best_ask="1.40") for i in range(100)]
    source = SyntheticSource(ticks)

    first = await run_backtest(
        strategy=always_back_below_two,
        params={"stake": Decimal("10")},
        source=source,
        time_range=_time_range(),
        clock=_fixed_clock,
    )
    second = await run_backtest(
        strategy=always_back_below_two,
        params={"stake": Decimal("10")},
        source=source,
        time_range=_time_range(),
        clock=_fixed_clock,
    )

    # No key filtering — structural equality on every key. This is the
    # whole point of the ``clock`` kwarg on ``run_backtest``.
    assert first == second
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

"""Unit tests for the mean-reversion reference strategy."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from algobet_common.schemas import MarketData, OrderSide, Venue
from backtest_engine.strategies.mean_reversion import on_tick


def _tick(mid: Decimal, *, spread: Decimal = Decimal("0.02")) -> MarketData:
    """Build a MarketData snapshot with a single bid/ask level centred on ``mid``."""
    half = spread / Decimal(2)
    bid = mid - half
    ask = mid + half
    return MarketData(
        venue=Venue.BETFAIR,
        market_id="1.234567",
        timestamp=datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        bids=[(bid, Decimal("10"))],
        asks=[(ask, Decimal("10"))],
    )


def _default_params() -> dict[str, Any]:
    return {
        "window_size": 30,
        "z_threshold": 1.5,
        "stake_gbp": "10",
        "venue": "betfair",
    }


def test_returns_none_during_warmup() -> None:
    params = _default_params()
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    for _ in range(29):
        assert on_tick(_tick(Decimal("2.00")), params, now) is None
    # The window has filled to 29 but not yet 30.
    assert len(params["_window"]) == 29


def test_emits_back_when_z_below_negative_threshold() -> None:
    params = _default_params()
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    # 29 ticks oscillating around 2.00 with small noise to produce a
    # non-zero stddev, then a 30th tick well below the mean.
    highs = [Decimal("2.01"), Decimal("1.99")] * 14 + [Decimal("2.01")]
    assert len(highs) == 29
    for mid in highs:
        assert on_tick(_tick(mid), params, now) is None
    signal = on_tick(_tick(Decimal("1.80")), params, now)
    assert signal is not None
    assert signal.side == OrderSide.BACK
    # BACK price is the best_ask of the triggering tick (mid 1.80 + 0.01).
    assert signal.price == Decimal("1.81")
    assert signal.stake == Decimal("10")
    assert signal.venue == Venue.BETFAIR


def test_emits_lay_when_z_above_positive_threshold() -> None:
    params = _default_params()
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    lows = [Decimal("2.01"), Decimal("1.99")] * 14 + [Decimal("1.99")]
    assert len(lows) == 29
    for mid in lows:
        assert on_tick(_tick(mid), params, now) is None
    signal = on_tick(_tick(Decimal("2.20")), params, now)
    assert signal is not None
    assert signal.side == OrderSide.LAY
    # LAY price is the best_bid of the triggering tick (mid 2.20 - 0.01).
    assert signal.price == Decimal("2.19")
    assert signal.stake == Decimal("10")


def test_returns_none_on_constant_price_window() -> None:
    params = _default_params()
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    for _ in range(30):
        # All ticks at identical mid → stddev == 0 → no signal ever.
        assert on_tick(_tick(Decimal("2.00")), params, now) is None


def test_returns_none_on_missing_book_side() -> None:
    params = _default_params()
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    no_asks = MarketData(
        venue=Venue.BETFAIR,
        market_id="1.234567",
        timestamp=now,
        bids=[(Decimal("1.99"), Decimal("10"))],
        asks=[],
    )
    no_bids = MarketData(
        venue=Venue.BETFAIR,
        market_id="1.234567",
        timestamp=now,
        bids=[],
        asks=[(Decimal("2.01"), Decimal("10"))],
    )
    assert on_tick(no_asks, params, now) is None
    assert on_tick(no_bids, params, now) is None
    # Short-circuit must happen before the window is touched.
    assert "_window" not in params or params["_window"] == []


def test_window_accumulates_across_calls() -> None:
    params = _default_params()
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    for i in range(35):
        # Alternating mids produce a non-degenerate window.
        mid = Decimal("2.00") + (Decimal("0.01") if i % 2 == 0 else Decimal("-0.01"))
        on_tick(_tick(mid), params, now)
    # The window is trimmed to window_size, and the caller observes it —
    # this is the contract Phase 6c relies on.
    assert len(params["_window"]) == 30


def test_window_list_identity_preserved() -> None:
    """The strategy mutates params['_window'] in place rather than rebinding."""
    params = _default_params()
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    on_tick(_tick(Decimal("2.00")), params, now)
    first_ref = params["_window"]
    on_tick(_tick(Decimal("2.01")), params, now)
    assert params["_window"] is first_ref


def test_no_signal_when_z_within_threshold() -> None:
    params = _default_params()
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    mids = [Decimal("2.01"), Decimal("1.99")] * 15
    assert len(mids) == 30
    last_signal = None
    for mid in mids:
        last_signal = on_tick(_tick(mid), params, now)
    # The final mid is 1.99 — well inside ±1.5 stddev of mean 2.00.
    assert last_signal is None


@pytest.mark.parametrize("stake_input", ["10", "25.5", 10])
def test_stake_coerced_to_decimal(stake_input: Any) -> None:
    params = _default_params()
    params["stake_gbp"] = stake_input
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    mids = [Decimal("2.01"), Decimal("1.99")] * 14 + [Decimal("2.01")]
    for mid in mids:
        on_tick(_tick(mid), params, now)
    signal = on_tick(_tick(Decimal("1.80")), params, now)
    assert signal is not None
    assert signal.stake == Decimal(str(stake_input))

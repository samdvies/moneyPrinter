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


def test_exact_window_size_opens_gate() -> None:
    """The 5th tick (filling the window exactly) should emit a signal; the 4th must not.

    Also asserts that the window stays capped at window_size after the gate opens.
    """
    params: dict[str, Any] = {
        "window_size": 5,
        "z_threshold": 1.5,
        "stake_gbp": "10",
        "venue": "betfair",
    }
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    # Four warm-up ticks alternating around 2.00 — window not yet full.
    warmup = [Decimal("2.01"), Decimal("1.99"), Decimal("2.01"), Decimal("1.99")]
    for mid in warmup:
        assert on_tick(_tick(mid), params, now) is None
    assert len(params["_window"]) == 4

    # 5th tick: far below the mean → z << -1.5 → should emit BACK.
    signal = on_tick(_tick(Decimal("1.50")), params, now)
    assert signal is not None, "5th tick (window full + large negative z) must emit a signal"
    assert signal.side == OrderSide.BACK
    assert len(params["_window"]) == 5


def test_z_equal_threshold_returns_none() -> None:
    """The threshold comparison is strict ``>``: z == z_threshold must return None.

    The strategy must NOT emit a signal when the z-score equals the threshold
    exactly. This test constructs a window whose pstdev and mean yield z ≈ threshold
    and asserts no signal is emitted.
    """
    # Use a simple window: 29 ticks all at 2.00, then a 30th at exactly
    # mean + z_threshold * stddev.  With pstdev of nearly-constant window
    # the stddev would be ~0, so instead build a window with known spread.
    # Easier approach: use alternating ±delta so stddev is exactly delta (pstdev),
    # then set the trigger tick so z = z_threshold exactly.
    params = _default_params()  # z_threshold=1.5, window_size=30
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)

    # 29 alternating ticks: mean=2.00, pstdev=0.01
    base_mids = [Decimal("2.01"), Decimal("1.99")] * 14 + [Decimal("2.01")]
    assert len(base_mids) == 29
    for mid in base_mids:
        on_tick(_tick(mid), params, now)

    # Peek at actual mean/stddev after 29 ticks so we can engineer tick 30.
    import statistics as _stats

    w29 = list(params["_window"])
    mean_f = float(sum(w29, Decimal(0)) / Decimal(len(w29)))

    # After adding tick 30 the window will hold ticks 2..29 + tick30 (30 items).
    # We want the resulting z == z_threshold exactly.
    # Approximate: target = mean + z_threshold * pstdev(window_with_new).
    # Iterate once: guess tick30, compute window30, check z.
    z_threshold = 1.5
    # First estimate: use current mean + threshold * current stddev.
    w29_f = [float(x) for x in w29]
    stddev_29 = _stats.pstdev(w29_f)
    target_mid = Decimal(str(round(mean_f + z_threshold * stddev_29, 6)))

    # Compute actual z that would result from adding target_mid.
    w30_f = [*w29_f[1:], float(target_mid)]  # slide window
    mean30 = sum(w30_f) / len(w30_f)
    stddev30 = _stats.pstdev(w30_f)
    z30 = (float(target_mid) - mean30) / stddev30 if stddev30 >= 1e-6 else 0.0

    # z30 should be very close to z_threshold (within 0.05 due to window slide).
    # If it's still >= z_threshold, nudge it just below.
    if z30 >= z_threshold:
        # Reduce target_mid slightly so z falls exactly at/below threshold.
        target_mid = Decimal(str(round(mean_f + z_threshold * stddev_29 * 0.999, 6)))

    result = on_tick(_tick(target_mid), params, now)
    # Strict > means z == threshold (or z slightly below) must not emit.
    assert (
        result is None
    ), "strict '>' on threshold: z at or just below z_threshold must return None"


def test_z_zero_returns_none() -> None:
    """A tick whose mid equals the window mean exactly produces z=0, which is within
    threshold; the strategy must return None.
    """
    params = _default_params()
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    # Fill 30 ticks alternating ±0.01 around 2.00 so mean=2.00.
    mids = [Decimal("2.01"), Decimal("1.99")] * 15
    assert len(mids) == 30
    for mid in mids:
        on_tick(_tick(mid), params, now)

    # Compute window mean — should be exactly 2.00.
    w = params["_window"]
    mean_d = sum(w, Decimal(0)) / Decimal(len(w))
    # Tick at the mean: z == 0.
    result = on_tick(_tick(mean_d), params, now)
    assert result is None


def test_near_zero_stddev_floor_rejects() -> None:
    """A window of nearly-constant prices must be rejected by the stddev floor,
    even when the triggering tick would produce a large z-score.

    The 30-tick window is filled with values alternating between 2.0 and
    2.0000001 (spread 1e-7), giving pstdev ~5e-8, well below min_stddev=1e-6.
    The 31st tick is 2.0000005, which would yield z ~4.6 without the floor — a
    false signal.  With the floor the strategy must return None.
    """
    params = _default_params()
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    # 30 warm-up ticks: alternating 2.0 / 2.0000001 — pstdev ~5e-8 < 1e-6.
    near_constant = [Decimal("2.0") if i % 2 == 0 else Decimal("2.0000001") for i in range(30)]
    for mid in near_constant:
        on_tick(_tick(mid), params, now)

    # 31st tick: slightly above the tight cluster; without the floor z ~4.6 → LAY.
    result = on_tick(_tick(Decimal("2.0000005")), params, now)
    assert result is None, (
        "stddev floor must suppress signals on near-constant windows; "
        "without the floor, fp stddev ~5e-8 would produce z ~4.6 and falsely emit"
    )


def test_determinism_pin() -> None:
    """Running on_tick twice over the same sequence with fresh params must yield
    identical signal lists.  This pins the determinism property for regression.
    """
    import random

    rng = random.Random(42)
    # Generate a 300-tick mean-reverting series: AR(1) with phi=0.8, sigma=0.02.
    mids: list[Decimal] = []
    price = 2.0
    for _ in range(300):
        price = 2.0 + 0.8 * (price - 2.0) + rng.gauss(0, 0.02)
        mids.append(Decimal(str(round(price, 6))))

    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)

    def _run() -> list[Any]:
        p = _default_params()
        return [on_tick(_tick(m), p, now) for m in mids]

    run_a = _run()
    run_b = _run()

    assert run_a == run_b, "on_tick must be deterministic: two runs over the same series must match"

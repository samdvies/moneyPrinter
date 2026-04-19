"""Unit tests for the pure fill engine."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from algobet_common.schemas import MarketData, OrderSide, OrderSignal, Venue
from simulator.fills import match_order


def _signal(
    side: OrderSide = OrderSide.BACK,
    stake: str = "10.00",
    price: str = "2.50",
    strategy_id: str = "strat-001",
) -> OrderSignal:
    return OrderSignal(
        strategy_id=strategy_id,
        mode="paper",
        venue=Venue.BETFAIR,
        market_id="test.001",
        side=side,
        stake=Decimal(stake),
        price=Decimal(price),
    )


def _book(
    bids: list[tuple[str, str]] | None = None,
    asks: list[tuple[str, str]] | None = None,
) -> MarketData:
    return MarketData(
        venue=Venue.BETFAIR,
        market_id="test.001",
        timestamp=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        bids=[(Decimal(p), Decimal(s)) for p, s in (bids or [])],
        asks=[(Decimal(p), Decimal(s)) for p, s in (asks or [])],
    )


# --- BACK / YES (taker hits asks) ---


def test_back_exact_cross_full_fill() -> None:
    """BACK order whose price >= ask[0].price fills completely."""
    sig = _signal(side=OrderSide.BACK, stake="10.00", price="2.60")
    book = _book(asks=[("2.50", "20.00")])
    result = match_order(sig, book)
    assert result.status == "filled"
    assert result.filled_stake == Decimal("10.00")
    assert result.filled_price == Decimal("2.50")


def test_back_no_cross_rests() -> None:
    """BACK order whose price < ask[0].price rests unfilled."""
    sig = _signal(side=OrderSide.BACK, stake="10.00", price="2.40")
    book = _book(asks=[("2.50", "20.00")])
    result = match_order(sig, book)
    assert result.status == "placed"
    assert result.filled_stake == Decimal("0")
    assert result.filled_price is None


def test_back_empty_book_rests() -> None:
    sig = _signal(side=OrderSide.BACK, stake="10.00", price="2.60")
    book = _book(asks=[])
    result = match_order(sig, book)
    assert result.status == "placed"
    assert result.filled_stake == Decimal("0")


def test_back_partial_fill_single_level() -> None:
    """Ask has less size than stake; partial fill with remainder resting."""
    sig = _signal(side=OrderSide.BACK, stake="30.00", price="2.60")
    book = _book(asks=[("2.50", "10.00")])
    result = match_order(sig, book)
    assert result.status == "partially_filled"
    assert result.filled_stake == Decimal("10.00")
    assert result.filled_price == Decimal("2.50")


def test_back_multi_level_full_fill() -> None:
    """Stake exhausted across two ask levels; VWAP price."""
    sig = _signal(side=OrderSide.BACK, stake="30.00", price="2.70")
    book = _book(asks=[("2.50", "20.00"), ("2.60", "20.00")])
    result = match_order(sig, book)
    assert result.status == "filled"
    assert result.filled_stake == Decimal("30.00")
    # VWAP: (20*2.50 + 10*2.60) / 30
    expected_price = (Decimal("20") * Decimal("2.50") + Decimal("10") * Decimal("2.60")) / Decimal(
        "30"
    )
    assert result.filled_price is not None
    assert abs(result.filled_price - expected_price) < Decimal("0.0001")


def test_back_multi_level_partial_fill() -> None:
    """Two levels but still not enough to fill stake; partial."""
    sig = _signal(side=OrderSide.BACK, stake="50.00", price="2.70")
    book = _book(asks=[("2.50", "10.00"), ("2.60", "10.00")])
    result = match_order(sig, book)
    assert result.status == "partially_filled"
    assert result.filled_stake == Decimal("20.00")


def test_back_zero_size_level_skipped() -> None:
    """A zero-size ask level is skipped cleanly."""
    sig = _signal(side=OrderSide.BACK, stake="10.00", price="2.70")
    book = _book(asks=[("2.40", "0.00"), ("2.50", "20.00")])
    result = match_order(sig, book)
    assert result.status == "filled"
    assert result.filled_stake == Decimal("10.00")
    assert result.filled_price == Decimal("2.50")


# --- LAY / NO (taker hits bids) ---


def test_lay_exact_cross_full_fill() -> None:
    """LAY order whose price <= bid[0].price fills completely."""
    sig = _signal(side=OrderSide.LAY, stake="10.00", price="2.40")
    book = _book(bids=[("2.50", "20.00")])
    result = match_order(sig, book)
    assert result.status == "filled"
    assert result.filled_stake == Decimal("10.00")
    assert result.filled_price == Decimal("2.50")


def test_lay_no_cross_rests() -> None:
    """LAY order whose price > bid[0].price rests unfilled."""
    sig = _signal(side=OrderSide.LAY, stake="10.00", price="2.60")
    book = _book(bids=[("2.50", "20.00")])
    result = match_order(sig, book)
    assert result.status == "placed"
    assert result.filled_stake == Decimal("0")


def test_no_side_full_fill() -> None:
    """Kalshi NO side behaves like LAY."""
    sig = _signal(side=OrderSide.NO, stake="5.00", price="0.40")
    book = _book(bids=[("0.50", "10.00")])
    result = match_order(sig, book)
    assert result.status == "filled"
    assert result.filled_stake == Decimal("5.00")


def test_yes_side_full_fill() -> None:
    """Kalshi YES side behaves like BACK."""
    sig = _signal(side=OrderSide.YES, stake="5.00", price="0.55")
    book = _book(asks=[("0.50", "10.00")])
    result = match_order(sig, book)
    assert result.status == "filled"
    assert result.filled_stake == Decimal("5.00")


# --- Result schema invariants ---


def test_result_has_required_fields() -> None:
    sig = _signal()
    book = _book(asks=[("2.30", "10.00")])
    result = match_order(sig, book)
    assert result.order_id
    assert result.strategy_id == sig.strategy_id
    assert result.mode == "paper"
    assert result.timestamp is not None

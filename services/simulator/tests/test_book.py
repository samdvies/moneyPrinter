"""Unit tests for the in-memory order book."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from algobet_common.schemas import MarketData, Venue
from simulator.book import Book


def _make_tick(
    market_id: str = "test.001",
    ts_offset_seconds: float = 0.0,
    bids: list[tuple[Decimal, Decimal]] | None = None,
    asks: list[tuple[Decimal, Decimal]] | None = None,
) -> MarketData:
    base = datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC)
    return MarketData(
        venue=Venue.BETFAIR,
        market_id=market_id,
        timestamp=base + timedelta(seconds=ts_offset_seconds),
        bids=bids or [(Decimal("2.50"), Decimal("100.0"))],
        asks=asks or [(Decimal("2.52"), Decimal("80.0"))],
    )


def test_update_and_get() -> None:
    book = Book()
    tick = _make_tick()
    book.update(tick)
    result = book.get(Venue.BETFAIR, "test.001")
    assert result is tick


def test_get_unknown_market_returns_none() -> None:
    book = Book()
    assert book.get(Venue.BETFAIR, "nonexistent") is None


def test_newer_update_replaces_older() -> None:
    book = Book()
    older = _make_tick(ts_offset_seconds=0.0, asks=[(Decimal("2.52"), Decimal("80.0"))])
    newer = _make_tick(ts_offset_seconds=1.0, asks=[(Decimal("2.60"), Decimal("50.0"))])
    book.update(older)
    book.update(newer)
    result = book.get(Venue.BETFAIR, "test.001")
    assert result is newer


def test_stale_update_ignored() -> None:
    book = Book()
    newer = _make_tick(ts_offset_seconds=5.0, asks=[(Decimal("2.60"), Decimal("50.0"))])
    older = _make_tick(ts_offset_seconds=0.0, asks=[(Decimal("2.52"), Decimal("80.0"))])
    book.update(newer)
    book.update(older)
    result = book.get(Venue.BETFAIR, "test.001")
    assert result is newer


def test_equal_timestamp_update_kept() -> None:
    """Same timestamp replaces (last-write-wins, no staleness)."""
    book = Book()
    tick1 = _make_tick(ts_offset_seconds=3.0)
    tick2 = _make_tick(ts_offset_seconds=3.0)
    book.update(tick1)
    book.update(tick2)
    result = book.get(Venue.BETFAIR, "test.001")
    assert result is tick2


def test_different_markets_independent() -> None:
    book = Book()
    tick_a = _make_tick(market_id="market.A")
    tick_b = _make_tick(market_id="market.B")
    book.update(tick_a)
    book.update(tick_b)
    assert book.get(Venue.BETFAIR, "market.A") is tick_a
    assert book.get(Venue.BETFAIR, "market.B") is tick_b


def test_different_venues_independent() -> None:
    book = Book()

    tick_bf = MarketData(
        venue=Venue.BETFAIR,
        market_id="m1",
        timestamp=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
    )
    tick_kal = MarketData(
        venue=Venue.KALSHI,
        market_id="m1",
        timestamp=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
    )
    book.update(tick_bf)
    book.update(tick_kal)
    assert book.get(Venue.BETFAIR, "m1") is tick_bf
    assert book.get(Venue.KALSHI, "m1") is tick_kal

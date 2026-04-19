from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from algobet_common.schemas import Venue
from ingestion.kalshi_adapter import kalshi_message_to_market_data


@pytest.fixture(autouse=True)
def _flush_redis() -> Iterator[None]:
    """Override Redis fixture: adapter mapping is pure and offline."""
    yield


def test_kalshi_message_to_market_data_happy_path() -> None:
    payload = {
        "market_ticker": "KXBTC-26APR",
        "timestamp": "2026-04-19T12:30:00Z",
        "bids": [{"price": "0.47", "size": "120"}, {"price": 0.46, "size": 75}],
        "asks": [{"price": "0.48", "size": "80"}],
        "last_trade": "0.475",
    }

    message = kalshi_message_to_market_data(payload)

    assert message is not None
    assert message.venue == Venue.KALSHI
    assert message.market_id == "KXBTC-26APR"
    assert message.timestamp == datetime(2026, 4, 19, 12, 30, tzinfo=UTC)
    assert message.bids == [(Decimal("0.47"), Decimal("120")), (Decimal("0.46"), Decimal("75"))]
    assert message.asks == [(Decimal("0.48"), Decimal("80"))]
    assert message.last_trade == Decimal("0.475")


def test_kalshi_message_to_market_data_empty_book() -> None:
    payload = {
        "market_ticker": "KXFED-26APR",
        "timestamp": "2026-04-19T12:31:00Z",
        "bids": [],
        "asks": [],
    }

    message = kalshi_message_to_market_data(payload)

    assert message is not None
    assert message.market_id == "KXFED-26APR"
    assert message.bids == []
    assert message.asks == []
    assert message.last_trade is None


def test_kalshi_message_to_market_data_ignores_malformed_payload() -> None:
    payload = {
        "timestamp": "not-a-timestamp",
        "bids": [{"price": "0.51"}],  # missing size
        "asks": "not-a-list",
    }

    message = kalshi_message_to_market_data(payload)

    assert message is None


def test_kalshi_message_to_market_data_handles_bad_iso_timestamp() -> None:
    payload = {
        "market_ticker": "KXBTC-26MAY",
        "timestamp": "not-a-timestamp",
        "bids": [],
        "asks": [],
    }

    message = kalshi_message_to_market_data(payload)

    assert message is not None
    assert message.market_id == "KXBTC-26MAY"
    assert message.timestamp.tzinfo is not None

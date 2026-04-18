from datetime import UTC, datetime
from decimal import Decimal

import pytest
from algobet_common.schemas import MarketData, OrderSide, OrderSignal, Venue
from pydantic import ValidationError


def test_market_data_roundtrip() -> None:
    msg = MarketData(
        venue=Venue.BETFAIR,
        market_id="1.234",
        timestamp=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
        bids=[(Decimal("2.50"), Decimal("100.0"))],
        asks=[(Decimal("2.52"), Decimal("80.0"))],
        last_trade=None,
    )
    as_json = msg.model_dump_json()
    restored = MarketData.model_validate_json(as_json)
    assert restored == msg


def test_order_signal_requires_mode() -> None:
    with pytest.raises(ValidationError):
        OrderSignal(  # type: ignore[call-arg]
            strategy_id="abc",
            venue=Venue.BETFAIR,
            market_id="1.234",
            side=OrderSide.BACK,
            stake=Decimal("10.0"),
            price=Decimal("2.5"),
        )


def test_order_signal_rejects_non_positive_stake() -> None:
    with pytest.raises(ValidationError):
        OrderSignal(
            strategy_id="abc",
            mode="paper",
            venue=Venue.BETFAIR,
            market_id="1.234",
            side=OrderSide.BACK,
            stake=Decimal("0"),
            price=Decimal("2.5"),
        )

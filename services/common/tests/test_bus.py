from datetime import UTC, datetime
from decimal import Decimal

import pytest

from algobet_common.bus import BusClient, Topic
from algobet_common.schemas import MarketData, Venue


@pytest.mark.asyncio
async def test_publish_and_consume_roundtrip(redis_url: str) -> None:
    client = BusClient(redis_url, service_name="test-service")
    await client.connect()
    try:
        msg = MarketData(
            venue=Venue.BETFAIR,
            market_id="test-market",
            timestamp=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
            bids=[(Decimal("1.5"), Decimal("50.0"))],
            asks=[(Decimal("1.6"), Decimal("30.0"))],
        )
        await client.publish(Topic.MARKET_DATA, msg)

        received = [
            received async for received in client.consume(
                Topic.MARKET_DATA, MarketData, count=1, block_ms=2000
            )
        ]
        assert len(received) == 1
        assert received[0].market_id == "test-market"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_consumer_group_isolation(redis_url: str) -> None:
    """Different service names form different consumer groups."""
    publisher = BusClient(redis_url, service_name="pub")
    await publisher.connect()
    try:
        msg = MarketData(
            venue=Venue.KALSHI,
            market_id="isolation-test",
            timestamp=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
        )
        await publisher.publish(Topic.MARKET_DATA, msg)
    finally:
        await publisher.close()

    # Two independent consumers should both see the message
    for name in ("svc-a", "svc-b"):
        c = BusClient(redis_url, service_name=name)
        await c.connect()
        try:
            received = [
                m async for m in c.consume(
                    Topic.MARKET_DATA, MarketData, count=1, block_ms=2000
                )
            ]
            assert any(m.market_id == "isolation-test" for m in received)
        finally:
            await c.close()

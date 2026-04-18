from decimal import Decimal

import pytest
from algobet_common.bus import BusClient, Topic
from algobet_common.schemas import MarketData
from ingestion.__main__ import publish_dummy_tick


@pytest.mark.asyncio
async def test_publish_dummy_tick_writes_to_market_data(redis_url: str) -> None:
    bus = BusClient(redis_url, service_name="ingestion-test")
    await bus.connect()
    try:
        await publish_dummy_tick(bus, market_id="smoke-1.234")

        received = [
            m async for m in bus.consume(Topic.MARKET_DATA, MarketData, count=1, block_ms=2000)
        ]
        assert received[0].market_id == "smoke-1.234"
        assert received[0].bids[0][0] == Decimal("2.50")
    finally:
        await bus.close()

from unittest.mock import AsyncMock

import pytest
from algobet_common.bus import Topic
from algobet_common.schemas import MarketData
from ingestion.__main__ import publish_synthetic_tick


@pytest.mark.asyncio
async def test_publish_synthetic_tick_writes_to_market_data() -> None:
    bus = AsyncMock()
    await publish_synthetic_tick(bus, market_id="smoke-1.234")

    bus.publish.assert_awaited_once()
    topic, message = bus.publish.await_args.args
    assert topic == Topic.MARKET_DATA
    assert isinstance(message, MarketData)
    assert message.market_id == "smoke-1.234"
    assert str(message.bids[0][0]) == "2.50"

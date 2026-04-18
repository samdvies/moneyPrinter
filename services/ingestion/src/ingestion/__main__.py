"""Ingestion entrypoint.

Phase 1 scaffolding: publishes a single dummy market.data tick so the
end-to-end bus path can be smoke-tested. Real Betfair/Kalshi feeds land
in Phase 2 per the design spec.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from algobet_common.bus import BusClient, Topic
from algobet_common.config import Settings
from algobet_common.schemas import MarketData, Venue


async def publish_dummy_tick(bus: BusClient, market_id: str = "scaffold.001") -> None:
    tick = MarketData(
        venue=Venue.BETFAIR,
        market_id=market_id,
        timestamp=datetime.now(UTC),
        bids=[(Decimal("2.50"), Decimal("100.0"))],
        asks=[(Decimal("2.52"), Decimal("80.0"))],
    )
    await bus.publish(Topic.MARKET_DATA, tick)


async def _main() -> None:
    settings = Settings()
    bus = BusClient(settings.redis_url, settings.service_name)
    await bus.connect()
    try:
        await publish_dummy_tick(bus)
        print(f"[{settings.service_name}] published dummy tick to {Topic.MARKET_DATA.value}")
    finally:
        await bus.close()


if __name__ == "__main__":
    asyncio.run(_main())

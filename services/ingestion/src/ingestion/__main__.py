"""Ingestion entrypoint."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from algobet_common.bus import BusClient, Topic
from algobet_common.config import Settings
from algobet_common.schemas import MarketData, Venue

from ingestion.betfair_adapter import (
    IngestionCredentialsError,
    run_betfair_stream_loop,
)


async def publish_synthetic_tick(bus: BusClient, market_id: str = "scaffold.001") -> None:
    tick = MarketData(
        venue=Venue.BETFAIR,
        market_id=market_id,
        timestamp=datetime.now(UTC),
        bids=[(Decimal("2.50"), Decimal("100.0"))],
        asks=[(Decimal("2.52"), Decimal("80.0"))],
    )
    await bus.publish(Topic.MARKET_DATA, tick)


async def publish_dummy_tick(bus: BusClient, market_id: str = "scaffold.001") -> None:
    """Backward-compatible alias retained for existing smoke/test entrypoints."""
    await publish_synthetic_tick(bus=bus, market_id=market_id)


async def run_ingestion_mode(*, bus: BusClient, settings: Settings) -> None:
    mode = settings.ingestion_mode.lower().strip()
    if mode == "synthetic":
        await publish_synthetic_tick(bus=bus)
        return

    if mode != "betfair":
        raise IngestionCredentialsError(
            "INGESTION_MODE must be one of: betfair, synthetic."
        )

    # TODO(CLAUDE.md Ground Rules): paper trading API must match live execution API
    # exactly so strategies remain mode-agnostic and promotion stays config-only.
    await run_betfair_stream_loop(
        bus=bus,
        username=settings.betfair_username or "",
        password=settings.betfair_password or "",
        app_key=settings.betfair_app_key or "",
        certs_dir=settings.betfair_certs_dir or "",
        market_ids=settings.betfair_market_ids,
        conflate_ms=settings.betfair_stream_conflate_ms,
        reconnect_delay_seconds=settings.betfair_reconnect_delay_seconds,
        poll_interval_seconds=settings.betfair_poll_interval_seconds,
    )


async def _main() -> None:
    settings = Settings()
    bus = BusClient(settings.redis_url, settings.service_name)
    await bus.connect()
    try:
        await run_ingestion_mode(bus=bus, settings=settings)
    except IngestionCredentialsError as exc:
        print(f"[{settings.service_name}] ingestion configuration error: {exc}")
        raise
    finally:
        await bus.close()


if __name__ == "__main__":
    asyncio.run(_main())

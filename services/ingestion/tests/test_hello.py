from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from algobet_common.bus import Topic
from algobet_common.config import Settings
from algobet_common.schemas import MarketData
from ingestion.__main__ import publish_synthetic_tick, run_ingestion_mode


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


@pytest.mark.asyncio
async def test_run_ingestion_mode_uses_synthetic_path(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AsyncMock()
    settings = cast(Settings, SimpleNamespace(ingestion_mode="synthetic"))
    publish = AsyncMock()
    betfair = AsyncMock()
    monkeypatch.setattr("ingestion.__main__.publish_synthetic_tick", publish)
    monkeypatch.setattr("ingestion.__main__.run_betfair_stream_loop", betfair)

    await run_ingestion_mode(bus=bus, settings=settings)

    publish.assert_awaited_once_with(bus=bus)
    betfair.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_ingestion_mode_uses_betfair_path(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AsyncMock()
    settings = cast(
        Settings,
        SimpleNamespace(
            ingestion_mode="betfair",
            betfair_username="user",
            betfair_password="pass",
            betfair_app_key="app",
            betfair_certs_dir="/certs",
            betfair_market_ids=["1.234"],
            betfair_stream_conflate_ms=0,
            betfair_reconnect_delay_seconds=5.0,
            betfair_poll_interval_seconds=0.25,
        ),
    )
    publish = AsyncMock()
    betfair = AsyncMock()
    monkeypatch.setattr("ingestion.__main__.publish_synthetic_tick", publish)
    monkeypatch.setattr("ingestion.__main__.run_betfair_stream_loop", betfair)

    await run_ingestion_mode(bus=bus, settings=settings)

    publish.assert_not_awaited()
    betfair.assert_awaited_once_with(
        bus=bus,
        username="user",
        password="pass",
        app_key="app",
        certs_dir="/certs",
        market_ids=["1.234"],
        conflate_ms=0,
        reconnect_delay_seconds=5.0,
        poll_interval_seconds=0.25,
    )

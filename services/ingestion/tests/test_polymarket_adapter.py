from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from algobet_common.schemas import Venue
from ingestion.polymarket_adapter import (
    PolymarketEgressError,
    check_egress_country,
    fetch_active_markets_page,
    gamma_market_to_market_data,
    publish_gamma_markets,
    run_polymarket_poll_loop,
)


@pytest.fixture(autouse=True)
def _flush_redis() -> Iterator[None]:
    """Override Redis fixture: adapter mapping is pure and offline."""
    yield


BINARY_MARKET_PAYLOAD = {
    "id": "540816",
    "conditionId": "0xcond",
    "question": "Russia-Ukraine Ceasefire before GTA VI?",
    "clobTokenIds": '["TOKEN_YES", "TOKEN_NO"]',
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.525", "0.475"]',
    "bestBid": 0.52,
    "bestAsk": 0.53,
    "lastTradePrice": 0.52,
    "active": True,
    "closed": False,
}


def test_gamma_market_to_market_data_emits_yes_and_no_messages() -> None:
    ts = datetime(2026, 4, 23, 12, 0, tzinfo=UTC)

    messages = gamma_market_to_market_data(BINARY_MARKET_PAYLOAD, timestamp=ts)

    assert len(messages) == 2

    yes, no = messages
    assert yes.venue == Venue.POLYMARKET
    assert yes.market_id == "TOKEN_YES"
    assert yes.timestamp == ts
    assert yes.bids == [(Decimal("0.52"), Decimal("0"))]
    assert yes.asks == [(Decimal("0.53"), Decimal("0"))]
    assert yes.last_trade == Decimal("0.52")

    assert no.venue == Venue.POLYMARKET
    assert no.market_id == "TOKEN_NO"
    assert no.bids == []
    assert no.asks == []
    assert no.last_trade == Decimal("0.475")


def test_gamma_market_to_market_data_handles_already_list_tokenids() -> None:
    payload = {
        **BINARY_MARKET_PAYLOAD,
        "clobTokenIds": ["A", "B"],
        "outcomePrices": ["0.9", "0.1"],
    }
    messages = gamma_market_to_market_data(payload)
    assert [m.market_id for m in messages] == ["A", "B"]
    assert messages[1].last_trade == Decimal("0.1")


def test_gamma_market_to_market_data_returns_empty_when_no_tokens() -> None:
    payload = {
        "conditionId": "0xbad",
        "clobTokenIds": "",
        "bestBid": 0.5,
    }
    assert gamma_market_to_market_data(payload) == []


def test_gamma_market_to_market_data_omits_missing_price_levels() -> None:
    payload = {
        **BINARY_MARKET_PAYLOAD,
        "bestBid": None,
        "bestAsk": None,
        "lastTradePrice": None,
    }
    messages = gamma_market_to_market_data(payload)
    assert messages[0].bids == []
    assert messages[0].asks == []
    assert messages[0].last_trade is None
    # NO still comes through via outcomePrices[1]
    assert messages[1].last_trade == Decimal("0.475")


def test_gamma_market_to_market_data_tolerates_malformed_json_string() -> None:
    payload = {"clobTokenIds": "[not-valid-json"}
    assert gamma_market_to_market_data(payload) == []


@pytest.mark.asyncio
async def test_publish_gamma_markets_forwards_all_mapped_messages() -> None:
    bus = AsyncMock()
    markets = [BINARY_MARKET_PAYLOAD, BINARY_MARKET_PAYLOAD]

    published = await publish_gamma_markets(bus, markets)

    assert published == 4
    assert bus.publish.await_count == 4


@pytest.mark.asyncio
async def test_check_egress_country_raises_for_blocked_country() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"country": "GB"}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(PolymarketEgressError):
            await check_egress_country(client)


@pytest.mark.asyncio
async def test_check_egress_country_returns_allowed_country() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"country": "nl"}))
    async with httpx.AsyncClient(transport=transport) as client:
        country = await check_egress_country(client)
        assert country == "NL"


@pytest.mark.asyncio
async def test_fetch_active_markets_page_uses_closed_false_filter() -> None:
    captured: dict[str, httpx.Request] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["req"] = request
        return httpx.Response(200, json=[BINARY_MARKET_PAYLOAD])

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        page = await fetch_active_markets_page(
            client,
            gamma_base_url="https://gamma-api.polymarket.com",
            limit=500,
            offset=0,
        )

    assert len(page) == 1
    req = captured["req"]
    assert req.url.path == "/markets"
    assert req.url.params["closed"] == "false"
    assert req.url.params["limit"] == "500"
    assert req.url.params["offset"] == "0"


@pytest.mark.asyncio
async def test_run_polymarket_poll_loop_publishes_and_stops_at_max_cycles() -> None:
    bus = AsyncMock()
    call_count = {"egress": 0, "markets": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ipinfo.io":
            call_count["egress"] += 1
            return httpx.Response(200, json={"country": "NL"})
        if request.url.path == "/markets":
            call_count["markets"] += 1
            if call_count["markets"] == 1:
                return httpx.Response(200, json=[BINARY_MARKET_PAYLOAD])
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        published = await run_polymarket_poll_loop(
            bus=bus,
            gamma_base_url="https://gamma-api.polymarket.com",
            poll_interval_seconds=0.0,
            page_size=500,
            http_client=client,
            max_cycles=1,
        )

    assert published == 2
    assert bus.publish.await_count == 2
    assert call_count["egress"] == 1


@pytest.mark.asyncio
async def test_run_polymarket_poll_loop_aborts_when_egress_blocked() -> None:
    bus = AsyncMock()
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"country": "GB"}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(PolymarketEgressError):
            await run_polymarket_poll_loop(
                bus=bus,
                gamma_base_url="https://gamma-api.polymarket.com",
                poll_interval_seconds=0.0,
                page_size=500,
                http_client=client,
                max_cycles=1,
            )
    assert bus.publish.await_count == 0

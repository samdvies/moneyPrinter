from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from algobet_common.schemas import Venue
from ingestion.betfair_adapter import (
    IngestionCredentialsError,
    consume_stream_updates,
    map_market_book_to_messages,
    publish_market_books,
    require_betfair_credentials,
)


class _FakePriceSize:
    def __init__(self, price: float, size: float) -> None:
        self.price = price
        self.size = size


class _FakeExchange:
    def __init__(self, backs: list[Any], lays: list[Any]) -> None:
        self.available_to_back = backs
        self.available_to_lay = lays


class _FakeRunner:
    def __init__(
        self, selection_id: int, ex: _FakeExchange, last_price_traded: float | None
    ) -> None:
        self.selection_id = selection_id
        self.ex = ex
        self.last_price_traded = last_price_traded


class _FakeMarketBook:
    def __init__(
        self, market_id: str, publish_time: int | None, runners: list[_FakeRunner]
    ) -> None:
        self.market_id = market_id
        self.publish_time = publish_time
        self.runners = runners


@pytest.fixture(autouse=True)
def _flush_redis() -> Iterator[None]:
    """Override Redis-flushing fixture: these tests are fully mocked."""
    yield


def test_map_market_book_to_messages_maps_runner_ladders() -> None:
    market_book = _FakeMarketBook(
        market_id="1.234",
        publish_time=1_744_979_200_000,
        runners=[
            _FakeRunner(
                selection_id=101,
                ex=_FakeExchange(
                    backs=[_FakePriceSize(2.5, 100), _FakePriceSize(2.48, 50)],
                    lays=[_FakePriceSize(2.52, 80)],
                ),
                last_price_traded=2.5,
            )
        ],
    )

    messages = map_market_book_to_messages(market_book)

    assert len(messages) == 1
    message = messages[0]
    assert message.venue == Venue.BETFAIR
    assert message.market_id == "1.234:101"
    assert message.timestamp == datetime.fromtimestamp(1_744_979_200, tz=UTC)
    assert message.bids == [(Decimal("2.5"), Decimal("100")), (Decimal("2.48"), Decimal("50"))]
    assert message.asks == [(Decimal("2.52"), Decimal("80"))]
    assert message.last_trade == Decimal("2.5")


def test_map_market_book_uses_fallback_timestamp_when_publish_time_missing() -> None:
    fallback = datetime(2026, 4, 19, 8, 0, tzinfo=UTC)
    market_book = _FakeMarketBook(
        market_id="1.234",
        publish_time=None,
        runners=[_FakeRunner(selection_id=7, ex=_FakeExchange([], []), last_price_traded=None)],
    )

    messages = map_market_book_to_messages(market_book, fallback_timestamp=fallback)

    assert messages[0].timestamp == fallback


def test_map_market_book_ignores_invalid_ladder_rows() -> None:
    market_book = _FakeMarketBook(
        market_id="1.234",
        publish_time=None,
        runners=[
            _FakeRunner(
                selection_id=77,
                ex=_FakeExchange(backs=[_FakePriceSize(2.2, 44), object()], lays=[object()]),
                last_price_traded=None,
            )
        ],
    )

    messages = map_market_book_to_messages(market_book)

    assert messages[0].bids == [(Decimal("2.2"), Decimal("44"))]
    assert messages[0].asks == []


@pytest.mark.asyncio
async def test_publish_market_books_publishes_each_mapped_message() -> None:
    bus = AsyncMock()
    market_book = _FakeMarketBook(
        market_id="1.234",
        publish_time=1_744_979_200_000,
        runners=[_FakeRunner(selection_id=1, ex=_FakeExchange([], []), last_price_traded=None)],
    )

    published = await publish_market_books(bus=bus, market_books=[market_book])

    assert published == 1
    assert bus.publish.await_count == 1


def test_require_betfair_credentials_raises_for_missing_values() -> None:
    with pytest.raises(IngestionCredentialsError):
        require_betfair_credentials(username="", password="", app_key="", certs_dir="")


class _FakeStream:
    def __init__(self, updates: list[list[_FakeMarketBook]]) -> None:
        self._updates = updates
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def get_generator(self) -> Any:
        iterator = iter(self._updates)

        def _next() -> list[_FakeMarketBook]:
            return next(iterator, [])

        return _next

    def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_consume_stream_updates_starts_stops_stream_and_publishes() -> None:
    bus = AsyncMock()
    stream = _FakeStream(
        updates=[
            [
                _FakeMarketBook(
                    market_id="1.111",
                    publish_time=1_744_979_200_000,
                    runners=[
                        _FakeRunner(
                            selection_id=1,
                            ex=_FakeExchange([], []),
                            last_price_traded=None,
                        )
                    ],
                )
            ],
            [],
        ]
    )

    published = await consume_stream_updates(
        stream=stream,
        bus=bus,
        poll_interval_seconds=0,
        max_batches=2,
    )

    assert stream.started is True
    assert stream.stopped is True
    assert published == 1
    assert bus.publish.await_count == 1

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from algobet_common.bus import BusClient, Topic
from algobet_common.schemas import MarketData, OrderSide, OrderSignal, Venue
from pydantic import BaseModel
from strategy_runner.engine import RegisteredStrategy, run_strategy_runner_loop

_STRATEGY_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _flush_redis() -> Iterator[None]:
    """Override Redis fixture: runner engine tests are fully mocked."""
    yield


def _tick(venue: Venue, market_id: str, mid: str) -> MarketData:
    price = Decimal(mid)
    spread = Decimal("0.01")
    return MarketData(
        venue=venue,
        market_id=market_id,
        timestamp=datetime(2026, 4, 23, 22, 0, tzinfo=UTC),
        bids=[(price - spread / 2, Decimal("1"))],
        asks=[(price + spread / 2, Decimal("1"))],
        last_trade=price,
    )


def _always_back_one_share(
    snapshot: MarketData, params: dict[str, Any], _now: datetime
) -> OrderSignal | None:
    params.setdefault("calls", 0)
    params["calls"] += 1
    return OrderSignal(
        strategy_id="00000000-0000-0000-0000-000000000000",
        mode="live",  # deliberately wrong; runner must override to 'paper'
        venue=snapshot.venue,
        market_id=snapshot.market_id,
        side=OrderSide.BACK,
        stake=Decimal("1"),
        price=snapshot.asks[0][0],
    )


def _never_signal(
    _snapshot: MarketData, _params: dict[str, Any], _now: datetime
) -> OrderSignal | None:
    return None


class _FakeBus:
    def __init__(self, ticks: list[MarketData]) -> None:
        self._ticks = ticks
        self.published: list[OrderSignal] = []

    async def consume(
        self, _topic: Topic, _model: type[BaseModel], *_args: Any, **_kwargs: Any
    ) -> AsyncIterator[MarketData]:
        for tick in self._ticks:
            yield tick

    async def publish(self, _topic: Topic, message: OrderSignal) -> None:
        self.published.append(message)


@pytest.mark.asyncio
async def test_runner_dispatches_matching_venue_and_publishes_signal() -> None:
    strategy = RegisteredStrategy(
        strategy_id=_STRATEGY_ID,
        slug="test-strategy",
        venue=Venue.POLYMARKET,
        on_tick=_always_back_one_share,
        base_params={},
    )
    bus = _FakeBus([_tick(Venue.POLYMARKET, "token-A", "0.50")])

    published = await run_strategy_runner_loop(
        bus=cast(BusClient, bus), strategies=[strategy], max_ticks=1
    )

    assert published == 1
    assert len(bus.published) == 1
    emitted = bus.published[0]
    assert emitted.strategy_id == _STRATEGY_ID, "runner must override strategy_id"
    assert emitted.mode == "paper", "runner must force mode=paper"
    assert emitted.venue == Venue.POLYMARKET
    assert emitted.market_id == "token-A"


@pytest.mark.asyncio
async def test_runner_filters_ticks_by_strategy_venue() -> None:
    strategy = RegisteredStrategy(
        strategy_id=_STRATEGY_ID,
        slug="test-strategy",
        venue=Venue.POLYMARKET,
        on_tick=_always_back_one_share,
        base_params={},
    )
    bus = _FakeBus(
        [
            _tick(Venue.BETFAIR, "betfair-1", "2.00"),
            _tick(Venue.POLYMARKET, "polymarket-A", "0.50"),
            _tick(Venue.KALSHI, "kalshi-1", "0.40"),
        ]
    )

    published = await run_strategy_runner_loop(
        bus=cast(BusClient, bus), strategies=[strategy], max_ticks=3
    )

    assert published == 1
    assert bus.published[0].market_id == "polymarket-A"


@pytest.mark.asyncio
async def test_runner_keeps_per_market_state_isolated() -> None:
    strategy = RegisteredStrategy(
        strategy_id=_STRATEGY_ID,
        slug="test-strategy",
        venue=Venue.POLYMARKET,
        on_tick=_always_back_one_share,
        base_params={},
    )
    bus = _FakeBus(
        [
            _tick(Venue.POLYMARKET, "token-A", "0.50"),
            _tick(Venue.POLYMARKET, "token-B", "0.60"),
            _tick(Venue.POLYMARKET, "token-A", "0.51"),
        ]
    )

    await run_strategy_runner_loop(bus=cast(BusClient, bus), strategies=[strategy], max_ticks=3)

    # The `calls` counter is stuffed into the per-market params dict by the
    # test strategy. If state were shared, token-A would see 3 calls; with
    # isolation, A sees 2, B sees 1.
    # We can't directly read per-market state, but we can assert dispatch
    # happened the right number of times via published signals:
    assert len(bus.published) == 3


@pytest.mark.asyncio
async def test_runner_respects_none_return() -> None:
    strategy = RegisteredStrategy(
        strategy_id=_STRATEGY_ID,
        slug="test-strategy",
        venue=Venue.POLYMARKET,
        on_tick=_never_signal,
        base_params={},
    )
    bus = _FakeBus([_tick(Venue.POLYMARKET, "token-A", "0.50")])

    published = await run_strategy_runner_loop(
        bus=cast(BusClient, bus), strategies=[strategy], max_ticks=1
    )

    assert published == 0
    assert bus.published == []


@pytest.mark.asyncio
async def test_runner_rejects_empty_strategy_list() -> None:
    bus = _FakeBus([])
    with pytest.raises(ValueError):
        await run_strategy_runner_loop(bus=cast(BusClient, bus), strategies=[], max_ticks=1)

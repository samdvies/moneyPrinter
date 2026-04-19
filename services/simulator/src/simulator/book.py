"""In-memory order book keyed by (venue, market_id).

Last-write-wins on timestamp; stale messages (older timestamp than cached)
are silently discarded.
"""

from __future__ import annotations

from algobet_common.schemas import MarketData, Venue


class Book:
    def __init__(self) -> None:
        self._data: dict[tuple[Venue, str], MarketData] = {}

    def update(self, tick: MarketData) -> None:
        key = (tick.venue, tick.market_id)
        existing = self._data.get(key)
        if existing is not None and tick.timestamp < existing.timestamp:
            return
        self._data[key] = tick

    def get(self, venue: Venue, market_id: str) -> MarketData | None:
        return self._data.get((venue, market_id))

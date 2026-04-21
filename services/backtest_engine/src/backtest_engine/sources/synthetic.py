"""In-memory ``TickSource`` for determinism tests and synthetic smoke runs.

``SyntheticSource`` holds a list of ``MarketData`` and replays any ticks
whose ``timestamp`` lies inside the (inclusive) ``time_range`` passed to
``iter_ticks``. It does not touch the database or the bus, so it is the
canonical source for unit-level harness tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from datetime import datetime

from algobet_common.schemas import MarketData


class SyntheticSource:
    """Replay a fixed list of ``MarketData`` ticks.

    The source is re-iterable: each call to ``iter_ticks`` yields a fresh
    async iterator over the stored ticks, so determinism tests can run the
    harness multiple times against the same source instance.
    """

    def __init__(self, ticks: Iterable[MarketData]) -> None:
        self._ticks: list[MarketData] = list(ticks)

    async def iter_ticks(
        self,
        time_range: tuple[datetime, datetime],
    ) -> AsyncIterator[MarketData]:
        start, end = time_range
        for tick in self._ticks:
            if start <= tick.timestamp <= end:
                yield tick

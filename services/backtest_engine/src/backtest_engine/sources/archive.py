"""``ArchiveSource`` — cursored replay over ``market_data_archive``.

Phase 6a only needs this to work against a seeded hypertable; 6b/6c will
tune the chunk-time interval and add compression policies. The cursor is
asyncpg's server-side cursor, which avoids materialising the full replay
range in memory.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Any

from algobet_common.db import Database
from algobet_common.schemas import MarketData, Venue


def _coerce_levels(raw: Any) -> list[tuple[Decimal, Decimal]]:
    """Convert a jsonb-decoded list-of-lists back into (Decimal, Decimal) pairs.

    asyncpg decodes jsonb arrays into Python lists; prices and sizes come
    back as floats/ints. Using ``Decimal(str(x))`` preserves precision while
    normalising the numeric type.
    """
    levels: list[tuple[Decimal, Decimal]] = []
    for entry in raw or []:
        price, size = entry[0], entry[1]
        levels.append((Decimal(str(price)), Decimal(str(size))))
    return levels


class ArchiveSource:
    """Replay the ``market_data_archive`` hypertable for a single venue.

    ``iter_ticks`` issues a single SELECT ordered by ``observed_at`` and
    streams rows via an asyncpg server-side cursor. Callers provide a
    closed ``[start, end]`` interval (timestamps inclusive).
    """

    def __init__(self, db: Database, venue: Venue | str) -> None:
        self._db = db
        self._venue = Venue(venue) if isinstance(venue, str) else venue

    async def iter_ticks(
        self,
        time_range: tuple[datetime, datetime],
    ) -> AsyncIterator[MarketData]:
        start, end = time_range
        async with self._db.acquire() as conn, conn.transaction():
            cursor = conn.cursor(
                """
                SELECT venue, market_id, observed_at, bids, asks, last_trade
                FROM market_data_archive
                WHERE observed_at >= $1
                  AND observed_at <= $2
                  AND venue = $3
                ORDER BY observed_at ASC
                """,
                start,
                end,
                self._venue.value,
            )
            async for row in cursor:
                last_trade = row["last_trade"]
                yield MarketData(
                    venue=Venue(row["venue"]),
                    market_id=row["market_id"],
                    timestamp=row["observed_at"],
                    bids=_coerce_levels(row["bids"]),
                    asks=_coerce_levels(row["asks"]),
                    last_trade=(Decimal(str(last_trade)) if last_trade is not None else None),
                )

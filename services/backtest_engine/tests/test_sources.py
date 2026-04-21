"""Tests for the ``SyntheticSource`` tick source.

``ArchiveSource`` requires a running Postgres/TimescaleDB; its integration
coverage lives in the Task 6a.4 end-to-end smoke. 6a.3 keeps the unit
surface focused on the deterministic in-memory source.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from algobet_common.schemas import MarketData, Venue
from backtest_engine.sources.synthetic import SyntheticSource


def _tick(offset_seconds: int) -> MarketData:
    return MarketData(
        venue=Venue.BETFAIR,
        market_id="test.001",
        timestamp=datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds),
        bids=[(Decimal("1.40"), Decimal("10"))],
        asks=[(Decimal("1.42"), Decimal("10"))],
    )


async def test_synthetic_source_yields_inside_range() -> None:
    ticks = [_tick(0), _tick(30), _tick(60)]
    source = SyntheticSource(ticks)
    start = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    end = start + timedelta(seconds=60)
    seen = [t async for t in source.iter_ticks((start, end))]
    assert len(seen) == 3


async def test_synthetic_source_filters_out_of_range() -> None:
    ticks = [_tick(-30), _tick(0), _tick(120)]
    source = SyntheticSource(ticks)
    start = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    end = start + timedelta(seconds=60)
    seen = [t async for t in source.iter_ticks((start, end))]
    assert len(seen) == 1
    assert seen[0].timestamp == start


async def test_synthetic_source_is_re_iterable() -> None:
    """Determinism tests rely on running the harness twice against one source."""
    ticks = [_tick(0), _tick(30)]
    source = SyntheticSource(ticks)
    start = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    end = start + timedelta(seconds=60)

    first = [t async for t in source.iter_ticks((start, end))]
    second = [t async for t in source.iter_ticks((start, end))]
    assert first == second

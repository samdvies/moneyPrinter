"""Tests for the ``SyntheticSource`` tick source.

``ArchiveSource`` requires a running Postgres/TimescaleDB; its integration
coverage lives in the Task 6a.4 end-to-end smoke. 6a.3 keeps the unit
surface focused on the deterministic in-memory source.

The private ``_coerce_levels`` helper from ``sources.archive`` is pure
and trivially testable without a DB — we probe it directly here
because it is the one piece of the archive path that can drift silently
(jsonb decode quirks, float precision) without integration coverage
catching it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from algobet_common.schemas import MarketData, Venue
from backtest_engine.sources.archive import _coerce_levels
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


def test_coerce_levels_round_trips_float_pairs() -> None:
    """jsonb-decoded list-of-lists become ``(Decimal, Decimal)`` tuples.

    ``_coerce_levels`` goes via ``Decimal(str(x))`` so the expected
    Decimals match what ``Decimal`` produces from the literal repr —
    no binary-float drift.
    """
    raw = [[2.5, 100.0], [2.52, 80.0]]
    assert _coerce_levels(raw) == [
        (Decimal("2.5"), Decimal("100.0")),
        (Decimal("2.52"), Decimal("80.0")),
    ]


def test_coerce_levels_empty_input_returns_empty() -> None:
    assert _coerce_levels([]) == []
    # The helper also accepts ``None`` (jsonb NULL) and treats it as empty.
    assert _coerce_levels(None) == []


def test_coerce_levels_uses_str_coercion_no_float_drift() -> None:
    """Passing ``0.1`` through ``Decimal(str(x))`` yields ``Decimal("0.1")``,
    not the binary-float approximation ``Decimal("0.1000000000000000055...")``.
    """
    out = _coerce_levels([[0.1, 0.2]])
    assert out == [(Decimal("0.1"), Decimal("0.2"))]

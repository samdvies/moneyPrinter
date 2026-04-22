"""Tests for spend_tracker.py — SQLite-backed daily xAI spend accounting.

All tests use an injected ``tmp_path`` for the DB file and an injected
``now`` callable to freeze/advance the clock across UTC midnight without
any monkey-patching of the real time module.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from research_orchestrator.spend_tracker import (
    MODEL_PRICING,
    SpendTracker,
    UnknownModelError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracker(tmp_path: Path, now: datetime) -> SpendTracker:
    """Return a SpendTracker backed by a temp DB with a frozen clock."""
    db_path = tmp_path / "spend.db"
    return SpendTracker(db_path=db_path, now=lambda: now)


def _tracker_with_clock(tmp_path: Path, clock_fn: Callable[[], datetime]) -> SpendTracker:
    """Return a SpendTracker backed by a temp DB with a mutable clock fn."""
    db_path = tmp_path / "spend.db"
    return SpendTracker(db_path=db_path, now=clock_fn)


# ---------------------------------------------------------------------------
# Known model ids in the pricing table
# ---------------------------------------------------------------------------

KNOWN_MODELS = list(MODEL_PRICING.keys())
# Use the first model in the table for generic cost tests.
_FIRST_MODEL = KNOWN_MODELS[0]


def _cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING[model]
    return (
        input_tokens * pricing.input_per_million + output_tokens * pricing.output_per_million
    ) / 1_000_000


# ---------------------------------------------------------------------------
# Test: fresh DB returns 0.0
# ---------------------------------------------------------------------------


def test_fresh_db_zero_cumulative(tmp_path: Path) -> None:
    now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    tracker = _tracker(tmp_path, now)
    assert tracker.cumulative_today_usd() == 0.0


# ---------------------------------------------------------------------------
# Test: record returns computed cost
# ---------------------------------------------------------------------------


def test_record_returns_computed_cost(tmp_path: Path) -> None:
    now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    tracker = _tracker(tmp_path, now)
    model = _FIRST_MODEL
    cost = tracker.record(model=model, input_tokens=1_000, output_tokens=500)
    expected = _cost(model, 1_000, 500)
    assert math.isclose(cost, expected, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Test: three events same day — cumulative equals sum of individual costs
# ---------------------------------------------------------------------------


def test_three_events_sum_correctly(tmp_path: Path) -> None:
    now = datetime(2026, 4, 22, 9, 0, 0, tzinfo=UTC)
    tracker = _tracker(tmp_path, now)
    model = _FIRST_MODEL

    c1 = tracker.record(model=model, input_tokens=1_000, output_tokens=200)
    c2 = tracker.record(model=model, input_tokens=2_000, output_tokens=400)
    c3 = tracker.record(model=model, input_tokens=500, output_tokens=100)

    expected_total = c1 + c2 + c3
    cumulative = tracker.cumulative_today_usd()
    assert math.isclose(cumulative, expected_total, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Test: events across UTC midnight — yesterday's events excluded
# ---------------------------------------------------------------------------


def test_events_across_midnight_only_today_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "spend.db"
    model = _FIRST_MODEL

    # Two events yesterday (2026-04-21 23:50 UTC)
    yesterday = datetime(2026, 4, 21, 23, 50, 0, tzinfo=UTC)
    tracker_yesterday = SpendTracker(db_path=db_path, now=lambda: yesterday)
    tracker_yesterday.record(model=model, input_tokens=10_000, output_tokens=5_000)
    tracker_yesterday.record(model=model, input_tokens=8_000, output_tokens=3_000)

    # One event today (2026-04-22 00:05 UTC) — same DB, clock advanced
    today = datetime(2026, 4, 22, 0, 5, 0, tzinfo=UTC)
    tracker_today = SpendTracker(db_path=db_path, now=lambda: today)
    today_cost = tracker_today.record(model=model, input_tokens=1_000, output_tokens=500)

    cumulative = tracker_today.cumulative_today_usd()
    assert math.isclose(
        cumulative, today_cost, rel_tol=1e-9
    ), f"Expected only today's cost {today_cost}, got {cumulative}"


# ---------------------------------------------------------------------------
# Test: would_exceed — true when current + estimate > cap
# ---------------------------------------------------------------------------


def test_would_exceed_true_when_over_cap(tmp_path: Path) -> None:
    now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    tracker = _tracker(tmp_path, now)
    model = _FIRST_MODEL

    # Fill up to near the cap
    tracker.record(model=model, input_tokens=100_000, output_tokens=50_000)
    cumulative = tracker.cumulative_today_usd()

    # Cap is exactly cumulative (so estimate > 0 will exceed)
    cap = cumulative
    assert tracker.would_exceed(estimated_usd=0.001, cap_usd=cap)


def test_would_exceed_false_when_under_cap(tmp_path: Path) -> None:
    now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    tracker = _tracker(tmp_path, now)
    model = _FIRST_MODEL

    tracker.record(model=model, input_tokens=1_000, output_tokens=200)
    cumulative = tracker.cumulative_today_usd()

    # Set a cap well above cumulative + estimate
    cap = cumulative + 100.0
    assert not tracker.would_exceed(estimated_usd=0.001, cap_usd=cap)


# ---------------------------------------------------------------------------
# Test: would_exceed — exact boundary (cumulative + estimate == cap → False)
# ---------------------------------------------------------------------------


def test_would_exceed_false_at_exact_boundary(tmp_path: Path) -> None:
    """Boundary: current + estimate == cap should NOT exceed (strict >)."""
    now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    tracker = _tracker(tmp_path, now)
    # No events recorded — cumulative == 0.0
    cap = 1.0
    # 0.0 + 1.0 == cap → should NOT exceed (strictly greater than is False)
    assert not tracker.would_exceed(estimated_usd=1.0, cap_usd=cap)


# ---------------------------------------------------------------------------
# Test: unknown model raises UnknownModelError
# ---------------------------------------------------------------------------


def test_unknown_model_raises(tmp_path: Path) -> None:
    now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    tracker = _tracker(tmp_path, now)
    with pytest.raises(UnknownModelError, match="gpt-4-turbo"):
        tracker.record(model="gpt-4-turbo", input_tokens=1_000, output_tokens=500)


# ---------------------------------------------------------------------------
# Test: DB file and parent dir are created on first use
# ---------------------------------------------------------------------------


def test_db_file_and_parent_dir_created(tmp_path: Path) -> None:
    nested_dir = tmp_path / "var" / "research_orchestrator"
    db_path = nested_dir / "spend.db"
    assert not nested_dir.exists(), "Pre-condition: directory must not exist yet"

    now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    tracker = SpendTracker(db_path=db_path, now=lambda: now)
    # Trigger DB initialisation by querying
    result = tracker.cumulative_today_usd()

    assert nested_dir.exists(), "Parent directory should have been created"
    assert db_path.exists(), "DB file should have been created"
    assert result == 0.0


# ---------------------------------------------------------------------------
# Test: pricing table covers the three required grok model ids
# ---------------------------------------------------------------------------


def test_pricing_table_covers_required_models() -> None:
    required = {"grok-4", "grok-4-fast-reasoning", "grok-4-fast-non-reasoning"}
    assert required.issubset(
        set(MODEL_PRICING.keys())
    ), f"Missing models in MODEL_PRICING: {required - set(MODEL_PRICING.keys())}"


# ---------------------------------------------------------------------------
# Test: multiple trackers share the same DB (persistence)
# ---------------------------------------------------------------------------


def test_persistence_across_tracker_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "spend.db"
    now = datetime(2026, 4, 22, 15, 0, 0, tzinfo=UTC)
    model = _FIRST_MODEL

    t1 = SpendTracker(db_path=db_path, now=lambda: now)
    cost = t1.record(model=model, input_tokens=5_000, output_tokens=2_000)

    # New instance, same DB path, same clock
    t2 = SpendTracker(db_path=db_path, now=lambda: now)
    assert math.isclose(t2.cumulative_today_usd(), cost, rel_tol=1e-9)

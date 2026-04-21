"""Integration test for research_orchestrator run_once.

Requires running Postgres and Redis. Skip gracefully if unavailable.

Phase 6b.4: the runner now loads the reference mean-reversion strategy
from ``wiki/30-Strategies/mean-reversion-ref.md`` and runs it through the
real harness against a deterministic AR(1) tick series. The advancement
gate is ``n_trades > 0 AND total_pnl_gbp > 0``, so the happy-path test
asserts promotion to ``paper`` on a strongly mean-reverting series and
the negative-path test asserts the strategy stays at ``hypothesis`` when
the series trends.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
import redis.asyncio as aioredis
from algobet_common.bus import Topic
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import MarketData
from research_orchestrator.runner import run_once
from strategy_registry import crud
from strategy_registry.models import Status, Strategy

pytestmark = pytest.mark.integration

_REFERENCE_SLUG = "mean-reversion-ref"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REFERENCE_WIKI_PATH = _REPO_ROOT / "wiki" / "30-Strategies" / "mean-reversion-ref.md"


@pytest.fixture(autouse=True)
def _snapshot_reference_wiki() -> Iterator[None]:
    """Snapshot + restore the reference wiki file around every integration test.

    Phase 6b.5 adds wiki write-back in ``runner.run_once``, which rewrites
    ``wiki/30-Strategies/mean-reversion-ref.md`` in place with fabricated
    backtest metrics. This fixture is module-local autouse (not
    package-wide) because only tests in this module dispatch ``run_once``
    against the real on-disk file; unit tests in sibling modules operate
    on ``tmp_path`` copies and must not pay the snapshot cost.
    """
    snapshot = _REFERENCE_WIKI_PATH.read_bytes() if _REFERENCE_WIKI_PATH.exists() else None
    try:
        yield
    finally:
        if snapshot is not None:
            _REFERENCE_WIKI_PATH.write_bytes(snapshot)


async def _find_by_slug(db: Database, slug: str) -> Strategy | None:
    """Look up a registry row by slug. ``crud`` exposes only ``get_strategy``
    (by UUID) and ``list_strategies``; in integration tests the slug is the
    stable key (the UUID rotates across CI runs)."""
    rows = await crud.list_strategies(db)
    for row in rows:
        if row.slug == slug:
            return row
    return None


async def test_run_once_mean_reverting_series_advances_to_paper(
    db: Database,
    bus: object,
    redis_url: str,
) -> None:
    """``run_once`` on the default (mean-reverting) series must:

    - Load the reference strategy from wiki (UPSERT → single registry row).
    - Seal a ``strategy_runs`` row with ``n_trades > 0`` and
      ``total_pnl_gbp > 0``.
    - Advance the strategy hypothesis → backtesting → paper.
    - Publish at least two ``ResearchEvent`` entries on the bus.
    """
    from algobet_common.bus import BusClient
    from algobet_common.db import Database

    assert isinstance(db, Database)
    assert isinstance(bus, BusClient)

    settings = Settings(service_name="research-orchestrator")
    await run_once(db, bus, settings)

    strategy = await _find_by_slug(db, _REFERENCE_SLUG)
    assert strategy is not None, "reference strategy must be upserted by run_once"
    assert strategy.status == Status.PAPER, (
        f"mean-reverting series must advance reference strategy to paper; "
        f"got status={strategy.status}"
    )

    # Verify the harness persisted a strategy_runs row with real metrics.
    async with db.acquire() as conn:
        run_row = await conn.fetchrow(
            """
            SELECT mode, ended_at, metrics
              FROM strategy_runs
             WHERE strategy_id = $1
             ORDER BY started_at DESC
             LIMIT 1
            """,
            strategy.id,
        )
    assert run_row is not None
    assert run_row["mode"] == "backtest"
    assert run_row["ended_at"] is not None

    metrics = run_row["metrics"]
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    assert int(metrics.get("n_ticks_consumed", 0)) > 0
    assert int(metrics.get("n_trades", 0)) > 0
    total_pnl = Decimal(str(metrics.get("total_pnl_gbp", "0")))
    assert total_pnl > Decimal(
        "0"
    ), f"mean-reverting series must produce positive realised P&L; got total_pnl_gbp={total_pnl}"

    # Redis: at least 2 ResearchEvents (backtesting + paper transitions).
    redis_client = aioredis.from_url(redis_url, decode_responses=True)
    try:
        entries = await redis_client.xread(
            streams={Topic.RESEARCH_EVENTS.value: "0"},
            count=100,
        )
        event_count = sum(len(stream_entries) for _stream, stream_entries in entries)
        assert (
            event_count >= 2
        ), f"Expected >= 2 ResearchEvent entries in {Topic.RESEARCH_EVENTS}; got {event_count}"
    finally:
        await redis_client.aclose()


async def test_run_once_trending_series_remains_hypothesis(
    db: Database,
    bus: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a strongly trending series the reference strategy must lose or
    break even, so the gate (``total_pnl_gbp > 0``) rejects and the
    strategy stays at ``hypothesis`` status.

    We force a trending series by monkey-patching the module-level tick
    builder — the strategy, harness, loader, and gate are all exercised
    unchanged, proving the gate is reachable and not a rubber-stamp.
    """
    import research_orchestrator.runner as runner_module
    from algobet_common.bus import BusClient
    from algobet_common.db import Database

    assert isinstance(db, Database)
    assert isinstance(bus, BusClient)

    # Keep a reference to the unpatched builder so the trending wrapper can
    # delegate to it with different parameters without recursing into itself.
    _original_builder = runner_module._build_mean_reverting_ticks

    def _trending_ticks(*_args: object, **_kwargs: object) -> list[MarketData]:
        # Zero pull + large positive drift → monotone up-trend; the
        # mean-reversion strategy fades rallies and never sees the
        # reversions it needs to close profitably. The ``*args / **kwargs``
        # absorb any call-shape the runner uses so the patch is sig-agnostic.
        return _original_builder(
            n_ticks=300,
            pull=0.0,
            noise=0.005,
            drift=Decimal("0.01"),
        )

    # Reset registry status if a prior test left the row at ``paper`` —
    # the state machine only allows hypothesis -> backtesting -> paper,
    # so we have to wipe any prior strategy_runs rows and reset the row
    # before the trending run can observe the "stays at hypothesis"
    # contract.  The wiki-loader UPSERT preserves status, so the runner
    # itself will not reset it.
    existing = await _find_by_slug(db, _REFERENCE_SLUG)
    if existing is not None and existing.status != Status.HYPOTHESIS:
        async with db.acquire() as conn:
            await conn.execute(
                "UPDATE strategies SET status = 'hypothesis' WHERE id = $1",
                existing.id,
            )

    # Patch the tick builder so run_once dispatches the trending series
    # through the same real harness + gate path as the happy test.
    monkeypatch.setattr(runner_module, "_build_mean_reverting_ticks", _trending_ticks)

    settings = Settings(service_name="research-orchestrator")
    await run_once(db, bus, settings)

    strategy = await _find_by_slug(db, _REFERENCE_SLUG)
    assert strategy is not None
    assert (
        strategy.status == Status.HYPOTHESIS
    ), f"trending series must leave reference strategy at hypothesis; got status={strategy.status}"

    async with db.acquire() as conn:
        run_row = await conn.fetchrow(
            """
            SELECT mode, ended_at, metrics
              FROM strategy_runs
             WHERE strategy_id = $1
             ORDER BY started_at DESC
             LIMIT 1
            """,
            strategy.id,
        )
    assert run_row is not None
    assert run_row["ended_at"] is not None
    metrics = run_row["metrics"]
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    total_pnl = Decimal(str(metrics.get("total_pnl_gbp", "0")))
    assert total_pnl <= Decimal(
        "0"
    ), f"trending series must produce non-positive realised P&L; got total_pnl_gbp={total_pnl}"

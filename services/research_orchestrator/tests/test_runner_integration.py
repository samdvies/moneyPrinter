"""Integration test for research_orchestrator run_once.

Requires running Postgres and Redis. Skip gracefully if unavailable.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import patch

import pytest
import redis.asyncio as aioredis
from algobet_common.bus import Topic
from algobet_common.config import Settings
from algobet_common.db import Database
from research_orchestrator.runner import run_once
from strategy_registry import crud
from strategy_registry.models import Status

pytestmark = pytest.mark.integration


async def test_run_once_creates_paper_strategy(
    db: Database,
    bus: object,
    redis_url: str,
) -> None:
    """run_once should create a strategy at status=paper, publish two
    ResearchEvents, and persist a strategy_runs row with real harness
    metrics (n_trades > 0, n_ticks_consumed > 0, ended_at populated)."""
    from algobet_common.bus import BusClient
    from algobet_common.db import Database

    assert isinstance(db, Database)
    assert isinstance(bus, BusClient)

    settings = Settings(service_name="research-orchestrator")

    await run_once(db, bus, settings)

    all_strategies = await crud.list_strategies(db)
    stub_strategies = [s for s in all_strategies if s.slug.startswith("stub-hypothesis-")]
    paper_strategies = [s for s in stub_strategies if s.status == Status.PAPER]
    assert (
        stub_strategies
    ), "Expected at least one paper strategy with slug starting 'stub-hypothesis-'"
    assert paper_strategies, "Expected at least one stub strategy promoted to paper"

    # No strategy should have been pushed to awaiting-approval or live.
    forbidden = [s for s in stub_strategies if s.status in (Status.AWAITING_APPROVAL, Status.LIVE)]
    assert (
        not forbidden
    ), f"Orchestrator must not create awaiting-approval or live strategies: {forbidden}"

    # Verify the harness persisted a strategy_runs row with real metrics.
    # Pick the most recent paper strategy created by this run and confirm
    # its backtest row is sealed (ended_at set) with non-stub metrics.
    latest_paper = max(paper_strategies, key=lambda s: s.created_at)
    async with db.acquire() as conn:
        run_row = await conn.fetchrow(
            """
            SELECT mode, ended_at, metrics
              FROM strategy_runs
             WHERE strategy_id = $1
             ORDER BY started_at DESC
             LIMIT 1
            """,
            latest_paper.id,
        )
    assert run_row is not None, f"Expected a strategy_runs row for strategy {latest_paper.id}"
    assert run_row["mode"] == "backtest"
    assert run_row["ended_at"] is not None, "Harness did not seal the strategy_runs row"
    metrics = run_row["metrics"]
    # asyncpg may return jsonb as str or dict depending on codec config; both
    # cases must contain the harness' fixed-shape keys.
    if isinstance(metrics, str):
        import json as _json

        metrics = _json.loads(metrics)
    assert metrics.get("n_ticks_consumed", 0) > 0
    assert (
        metrics.get("n_trades", 0) > 0
    ), "Expected trivial strategy to fire at least once against the synthetic best-ask-1.40 source"
    # The stub used to write status='stub'; the real harness never sets that
    # key, so promotion is no longer theatre.
    assert "status" not in metrics or metrics["status"] != "stub"

    # Verify Redis stream contains at least 2 entries (backtesting + paper events).
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


async def test_run_once_zero_trades_leaves_hypothesis(
    db: Database,
    bus: object,
) -> None:
    """When the synthetic source produces no fills (best ask 1.60 > trivial
    strategy threshold 1.50), run_once must leave the strategy at
    ``hypothesis`` status and persist a strategy_runs row with n_trades == 0.

    This test exercises the else-branch in ``runner.run_once``, proving that
    the n_trades > 0 gate is reachable and not a rubber-stamp.

    # TODO(6b): once Phase 6b lands with an ArchiveSource and a real edge
    # check, this synthetic override can be replaced by a genuine no-edge
    # scenario.
    """
    from algobet_common.bus import BusClient
    from algobet_common.db import Database

    assert isinstance(db, Database)
    assert isinstance(bus, BusClient)

    settings = Settings(service_name="research-orchestrator")

    # Patch the synthetic best-ask constant to 1.60 so the trivial strategy
    # (threshold <= 1.50) never fires, producing zero trades.
    import research_orchestrator.runner as runner_module

    with patch.object(runner_module, "_SYNTHETIC_BEST_ASK", Decimal("1.60")):
        await run_once(db, bus, settings)

    all_strategies = await crud.list_strategies(db)
    stub_strategies = [s for s in all_strategies if s.slug.startswith("stub-hypothesis-")]
    assert stub_strategies, "Expected at least one strategy to be created"

    # The strategy created under the 1.60 ask should still be at hypothesis.
    # We identify it by being the only one NOT at paper status (since the
    # happy-path test may have also run and created paper strategies).
    hypothesis_strategies = [s for s in stub_strategies if s.status == Status.HYPOTHESIS]
    assert hypothesis_strategies, (
        "Expected at least one strategy to remain at hypothesis status when "
        "best ask 1.60 produces zero trades"
    )

    # Verify the harness persisted a strategy_runs row with n_trades == 0.
    latest_hyp = max(hypothesis_strategies, key=lambda s: s.created_at)
    async with db.acquire() as conn:
        run_row = await conn.fetchrow(
            """
            SELECT mode, ended_at, metrics
              FROM strategy_runs
             WHERE strategy_id = $1
             ORDER BY started_at DESC
             LIMIT 1
            """,
            latest_hyp.id,
        )
    assert run_row is not None, f"Expected a strategy_runs row for strategy {latest_hyp.id}"
    assert run_row["mode"] == "backtest"
    assert run_row["ended_at"] is not None, "Harness did not seal the strategy_runs row"

    metrics = run_row["metrics"]
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    assert (
        str(metrics.get("n_trades", "missing")) == "0"
    ), f"Expected n_trades == 0 for zero-fill source; got {metrics.get('n_trades')}"

"""Integration test for research_orchestrator run_once.

Requires running Postgres and Redis.  Skip gracefully if unavailable.
"""

from __future__ import annotations

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
    """run_once should create a strategy at status=paper and publish two ResearchEvents."""
    from algobet_common.bus import BusClient
    from algobet_common.db import Database

    assert isinstance(db, Database)
    assert isinstance(bus, BusClient)

    settings = Settings(service_name="research-orchestrator")

    await run_once(db, bus, settings)

    all_strategies = await crud.list_strategies(db)
    stub_strategies = [s for s in all_strategies if s.slug.startswith("stub-hypothesis-")]
    paper_strategies = [s for s in stub_strategies if s.status == Status.PAPER]
    assert stub_strategies, (
        "Expected at least one paper strategy with slug starting 'stub-hypothesis-'"
    )
    assert paper_strategies, "Expected at least one stub strategy promoted to paper"

    # No strategy should have been pushed to awaiting-approval or live.
    forbidden = [
        s
        for s in stub_strategies
        if s.status in (Status.AWAITING_APPROVAL, Status.LIVE)
    ]
    assert not forbidden, (
        f"Orchestrator must not create awaiting-approval or live strategies: {forbidden}"
    )

    # Verify Redis stream contains at least 2 entries (backtesting + paper events).
    redis_client = aioredis.from_url(redis_url, decode_responses=True)
    try:
        entries = await redis_client.xread(
            streams={Topic.RESEARCH_EVENTS.value: "0"},
            count=100,
        )
        event_count = sum(len(stream_entries) for _stream, stream_entries in entries)
        assert event_count >= 2, (
            f"Expected >= 2 ResearchEvent entries in {Topic.RESEARCH_EVENTS}; got {event_count}"
        )
    finally:
        await redis_client.aclose()

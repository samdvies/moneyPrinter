"""Integration tests for strategy_registry CRUD — requires Postgres."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
from algobet_common.db import Database
from strategy_registry.crud import (
    create_strategy,
    end_run,
    get_strategy,
    list_strategies,
    start_run,
    transition,
)
from strategy_registry.errors import (
    ApprovalRequiredError,
    InvalidTransitionError,
    StrategyNotFoundError,
)
from strategy_registry.models import Mode, Status

pytestmark = pytest.mark.integration


@pytest.fixture
async def db(postgres_dsn: str, require_postgres: None) -> AsyncGenerator[Database, None]:
    database = Database(postgres_dsn)
    await database.connect()
    yield database
    await database.close()


def unique_slug(prefix: str = "test") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Happy-path lifecycle: hypothesis → backtesting → paper → awaiting-approval → live
# ---------------------------------------------------------------------------


async def test_full_happy_path(db: Database) -> None:
    slug = unique_slug("happy")
    strategy = await create_strategy(db, slug=slug, parameters={"alpha": 0.1})

    assert strategy.status == Status.HYPOTHESIS
    assert strategy.approved_by is None
    assert strategy.approved_at is None

    s = await transition(db, strategy.id, Status.BACKTESTING)
    assert s.status == Status.BACKTESTING

    s = await transition(db, strategy.id, Status.PAPER)
    assert s.status == Status.PAPER

    s = await transition(db, strategy.id, Status.AWAITING_APPROVAL)
    assert s.status == Status.AWAITING_APPROVAL

    s = await transition(db, strategy.id, Status.LIVE, approved_by="operator@test")
    assert s.status == Status.LIVE
    assert s.approved_by == "operator@test"
    assert s.approved_at is not None

    # Verify via a fresh DB read
    fetched = await get_strategy(db, strategy.id)
    assert fetched.status == Status.LIVE
    assert fetched.approved_by == "operator@test"
    assert fetched.approved_at is not None


# ---------------------------------------------------------------------------
# create_strategy defaults
# ---------------------------------------------------------------------------


async def test_create_strategy_defaults(db: Database) -> None:
    slug = unique_slug("defaults")
    s = await create_strategy(db, slug=slug)
    assert s.status == Status.HYPOTHESIS
    assert s.parameters == {}
    assert s.wiki_path is None


async def test_create_strategy_with_wiki_path(db: Database) -> None:
    slug = unique_slug("wiki")
    s = await create_strategy(db, slug=slug, wiki_path="wiki/30-Strategies/test.md")
    assert s.wiki_path == "wiki/30-Strategies/test.md"


# ---------------------------------------------------------------------------
# get_strategy
# ---------------------------------------------------------------------------


async def test_get_strategy_not_found(db: Database) -> None:
    with pytest.raises(StrategyNotFoundError):
        await get_strategy(db, uuid.uuid4())


# ---------------------------------------------------------------------------
# list_strategies
# ---------------------------------------------------------------------------


async def test_list_strategies(db: Database) -> None:
    slugs = [unique_slug("list") for _ in range(3)]
    for slug in slugs:
        await create_strategy(db, slug=slug)

    all_strategies = await list_strategies(db)
    all_slugs = {s.slug for s in all_strategies}
    for slug in slugs:
        assert slug in all_slugs


async def test_list_strategies_filtered_by_status(db: Database) -> None:
    slug = unique_slug("filtered")
    s = await create_strategy(db, slug=slug)
    await transition(db, s.id, Status.BACKTESTING)

    backtesting = await list_strategies(db, status=Status.BACKTESTING)
    ids = {row.id for row in backtesting}
    assert s.id in ids

    hypothesis = await list_strategies(db, status=Status.HYPOTHESIS)
    assert s.id not in {row.id for row in hypothesis}


# ---------------------------------------------------------------------------
# Negative: invalid transition (paper → live skipping awaiting-approval)
# ---------------------------------------------------------------------------


async def test_paper_to_live_raises_invalid_transition(db: Database) -> None:
    slug = unique_slug("neg-paper-live")
    s = await create_strategy(db, slug=slug)
    await transition(db, s.id, Status.BACKTESTING)
    await transition(db, s.id, Status.PAPER)

    with pytest.raises(InvalidTransitionError):
        await transition(db, s.id, Status.LIVE, approved_by="operator@test")

    # DB row must be unchanged
    fetched = await get_strategy(db, s.id)
    assert fetched.status == Status.PAPER


# ---------------------------------------------------------------------------
# Negative: awaiting-approval → live without approved_by
# ---------------------------------------------------------------------------


async def test_live_without_approved_by_raises(db: Database) -> None:
    slug = unique_slug("neg-approval")
    s = await create_strategy(db, slug=slug)
    await transition(db, s.id, Status.BACKTESTING)
    await transition(db, s.id, Status.PAPER)
    await transition(db, s.id, Status.AWAITING_APPROVAL)

    with pytest.raises(ApprovalRequiredError):
        await transition(db, s.id, Status.LIVE, approved_by=None)

    fetched = await get_strategy(db, s.id)
    assert fetched.status == Status.AWAITING_APPROVAL
    assert fetched.approved_by is None
    assert fetched.approved_at is None


# ---------------------------------------------------------------------------
# Negative: transition on non-existent strategy
# ---------------------------------------------------------------------------


async def test_transition_not_found(db: Database) -> None:
    with pytest.raises(StrategyNotFoundError):
        await transition(db, uuid.uuid4(), Status.BACKTESTING)


# ---------------------------------------------------------------------------
# Retired strategies cannot transition further
# ---------------------------------------------------------------------------


async def test_retired_is_terminal(db: Database) -> None:
    slug = unique_slug("retired")
    s = await create_strategy(db, slug=slug)
    await transition(db, s.id, Status.BACKTESTING)
    await transition(db, s.id, Status.RETIRED)

    with pytest.raises(InvalidTransitionError):
        await transition(db, s.id, Status.PAPER)


# ---------------------------------------------------------------------------
# start_run / end_run
# ---------------------------------------------------------------------------


async def test_start_and_end_run(db: Database) -> None:
    slug = unique_slug("run")
    s = await create_strategy(db, slug=slug)

    run = await start_run(db, s.id, Mode.BACKTEST, metrics={"initial": 1})
    assert run.strategy_id == s.id
    assert run.mode == Mode.BACKTEST
    assert run.ended_at is None

    ended = await end_run(db, run.id, metrics={"sharpe": 1.5})
    assert ended.ended_at is not None
    assert ended.metrics["sharpe"] == 1.5


# ---------------------------------------------------------------------------
# Concurrent update test (TOCTOU guard)
# ---------------------------------------------------------------------------


async def test_concurrent_transition_only_one_succeeds(db: Database) -> None:
    """Two coroutines race to transition the same strategy; exactly one must win."""
    slug = unique_slug("concurrent")
    s = await create_strategy(db, slug=slug)
    await transition(db, s.id, Status.BACKTESTING)
    await transition(db, s.id, Status.PAPER)
    await transition(db, s.id, Status.AWAITING_APPROVAL)

    results: list[Exception | None] = []

    async def try_go_live() -> None:
        try:
            await transition(db, s.id, Status.LIVE, approved_by="operator@test")
            results.append(None)
        except Exception as exc:
            results.append(exc)

    await asyncio.gather(try_go_live(), try_go_live())

    successes = [r for r in results if r is None]
    failures = [r for r in results if r is not None]
    assert len(successes) == 1, f"Expected 1 success, got {successes}"
    assert len(failures) == 1
    assert isinstance(failures[0], InvalidTransitionError)

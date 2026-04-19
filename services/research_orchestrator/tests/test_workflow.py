"""Unit tests for research_orchestrator workflow state-machine wiring.

These tests are offline (no DB, no Redis).  All external calls are mocked.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from research_orchestrator.errors import OrchestratorError
from research_orchestrator.workflow import hypothesize, promote, run_backtest
from strategy_registry.models import Status, Strategy

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# hypothesize
# ---------------------------------------------------------------------------


async def test_hypothesize_returns_stub() -> None:
    result = await hypothesize()
    assert "name" in result
    assert "description" in result
    assert "venue" in result


# ---------------------------------------------------------------------------
# run_backtest
# ---------------------------------------------------------------------------


async def test_run_backtest_returns_stub() -> None:
    result = await run_backtest({"name": "x"})
    assert result["status"] == "stub"
    assert "sharpe" in result


# ---------------------------------------------------------------------------
# promote — forbidden transitions
# ---------------------------------------------------------------------------


async def test_promote_blocks_live_transition() -> None:
    db = MagicMock()
    bus = MagicMock()
    with patch("research_orchestrator.workflow.crud") as mock_crud:
        with pytest.raises(OrchestratorError):
            await promote(db, bus, uuid.uuid4(), Status.LIVE)
        mock_crud.get_strategy.assert_not_called()
        mock_crud.transition.assert_not_called()


async def test_promote_blocks_awaiting_approval_transition() -> None:
    db = MagicMock()
    bus = MagicMock()
    with patch("research_orchestrator.workflow.crud") as mock_crud:
        with pytest.raises(OrchestratorError):
            await promote(db, bus, uuid.uuid4(), Status.AWAITING_APPROVAL)
        mock_crud.get_strategy.assert_not_called()
        mock_crud.transition.assert_not_called()


# ---------------------------------------------------------------------------
# promote — allowed transitions
# ---------------------------------------------------------------------------


def _make_strategy(status: Status) -> Strategy:
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    return Strategy(
        id=uuid.uuid4(),
        slug="test",
        status=status,
        created_at=now,
        updated_at=now,
    )


async def test_promote_allowed_backtesting() -> None:
    db = MagicMock()
    bus = MagicMock()
    bus.publish = AsyncMock()

    strategy_id = uuid.uuid4()
    hypothesis_strategy = _make_strategy(Status.HYPOTHESIS)
    backtesting_strategy = _make_strategy(Status.BACKTESTING)

    with patch("research_orchestrator.workflow.crud") as mock_crud:
        mock_crud.get_strategy = AsyncMock(return_value=hypothesis_strategy)
        mock_crud.transition = AsyncMock(return_value=backtesting_strategy)

        result = await promote(db, bus, strategy_id, Status.BACKTESTING)

    mock_crud.transition.assert_called_once()
    call_kwargs = mock_crud.transition.call_args
    actual = call_kwargs.args[2] if call_kwargs.args else call_kwargs.kwargs.get("to_status")
    assert actual == Status.BACKTESTING

    bus.publish.assert_called_once()
    from algobet_common.bus import Topic
    from research_orchestrator.schemas import ResearchEvent

    publish_args = bus.publish.call_args.args
    assert publish_args[0] == Topic.RESEARCH_EVENTS
    assert isinstance(publish_args[1], ResearchEvent)
    assert result == backtesting_strategy


async def test_promote_allowed_paper() -> None:
    db = MagicMock()
    bus = MagicMock()
    bus.publish = AsyncMock()

    strategy_id = uuid.uuid4()
    backtesting_strategy = _make_strategy(Status.BACKTESTING)
    paper_strategy = _make_strategy(Status.PAPER)

    with patch("research_orchestrator.workflow.crud") as mock_crud:
        mock_crud.get_strategy = AsyncMock(return_value=backtesting_strategy)
        mock_crud.transition = AsyncMock(return_value=paper_strategy)

        result = await promote(db, bus, strategy_id, Status.PAPER)

    mock_crud.transition.assert_called_once()
    call_kwargs = mock_crud.transition.call_args
    actual = call_kwargs.args[2] if call_kwargs.args else call_kwargs.kwargs.get("to_status")
    assert actual == Status.PAPER

    bus.publish.assert_called_once()
    from algobet_common.bus import Topic
    from research_orchestrator.schemas import ResearchEvent

    publish_args = bus.publish.call_args.args
    assert publish_args[0] == Topic.RESEARCH_EVENTS
    assert isinstance(publish_args[1], ResearchEvent)
    assert result == paper_strategy

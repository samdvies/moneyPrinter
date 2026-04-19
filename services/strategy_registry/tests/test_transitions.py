"""Pure unit tests for transitions.validate_transition — no DB required."""

import pytest
from strategy_registry.errors import ApprovalRequiredError, InvalidTransitionError
from strategy_registry.models import Status
from strategy_registry.transitions import validate_transition

# ---------------------------------------------------------------------------
# Allowed edges — should not raise
# ---------------------------------------------------------------------------


def test_hypothesis_to_backtesting() -> None:
    validate_transition(Status.HYPOTHESIS, Status.BACKTESTING)


def test_backtesting_to_paper() -> None:
    validate_transition(Status.BACKTESTING, Status.PAPER)


def test_backtesting_to_retired() -> None:
    validate_transition(Status.BACKTESTING, Status.RETIRED)


def test_paper_to_awaiting_approval() -> None:
    validate_transition(Status.PAPER, Status.AWAITING_APPROVAL)


def test_paper_to_retired() -> None:
    validate_transition(Status.PAPER, Status.RETIRED)


def test_awaiting_approval_to_live() -> None:
    validate_transition(Status.AWAITING_APPROVAL, Status.LIVE, approved_by="operator@test")


def test_awaiting_approval_to_retired() -> None:
    validate_transition(Status.AWAITING_APPROVAL, Status.RETIRED)


def test_live_to_retired() -> None:
    validate_transition(Status.LIVE, Status.RETIRED)


# ---------------------------------------------------------------------------
# Disallowed edges — must raise InvalidTransitionError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "to"),
    [
        (Status.HYPOTHESIS, Status.LIVE),
        (Status.HYPOTHESIS, Status.PAPER),
        (Status.HYPOTHESIS, Status.AWAITING_APPROVAL),
        (Status.HYPOTHESIS, Status.RETIRED),
        (Status.BACKTESTING, Status.HYPOTHESIS),
        (Status.BACKTESTING, Status.LIVE),
        (Status.BACKTESTING, Status.AWAITING_APPROVAL),
        (Status.PAPER, Status.LIVE),  # must go through awaiting-approval first
        (Status.PAPER, Status.HYPOTHESIS),
        (Status.PAPER, Status.BACKTESTING),
        (Status.AWAITING_APPROVAL, Status.HYPOTHESIS),
        (Status.AWAITING_APPROVAL, Status.BACKTESTING),
        (Status.AWAITING_APPROVAL, Status.PAPER),
        (Status.LIVE, Status.HYPOTHESIS),
        (Status.LIVE, Status.BACKTESTING),
        (Status.LIVE, Status.PAPER),
        (Status.LIVE, Status.AWAITING_APPROVAL),
        (Status.LIVE, Status.LIVE),
        (Status.RETIRED, Status.HYPOTHESIS),
        (Status.RETIRED, Status.LIVE),
    ],
)
def test_disallowed_transition_raises(current: Status, to: Status) -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(current, to, approved_by="operator@test")


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------


def test_live_without_approved_by_raises_approval_required() -> None:
    with pytest.raises(ApprovalRequiredError):
        validate_transition(Status.AWAITING_APPROVAL, Status.LIVE, approved_by=None)


def test_live_with_empty_string_approved_by_raises_approval_required() -> None:
    with pytest.raises(ApprovalRequiredError):
        validate_transition(Status.AWAITING_APPROVAL, Status.LIVE, approved_by="")


def test_live_with_valid_approved_by_does_not_raise() -> None:
    # Ensure a non-empty approved_by passes the guard
    validate_transition(Status.AWAITING_APPROVAL, Status.LIVE, approved_by="human@example.com")


# ---------------------------------------------------------------------------
# String inputs (the function accepts str as well as Status)
# ---------------------------------------------------------------------------


def test_accepts_string_inputs() -> None:
    validate_transition("hypothesis", "backtesting")


def test_invalid_string_transition_raises() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition("paper", "live")

"""Pure lifecycle state machine for strategy status transitions.

No DB access in this module — it exists solely so the promotion-gate auditor
can verify correctness without spinning up a database.
"""

from __future__ import annotations

from .errors import ApprovalRequiredError, InvalidTransitionError
from .models import Status

# Declarative transition map: current_status -> set of allowed next statuses
_ALLOWED: dict[Status, set[Status]] = {
    Status.HYPOTHESIS: {Status.BACKTESTING},
    Status.BACKTESTING: {Status.PAPER, Status.RETIRED},
    Status.PAPER: {Status.AWAITING_APPROVAL, Status.RETIRED},
    Status.AWAITING_APPROVAL: {Status.LIVE, Status.RETIRED},
    Status.LIVE: {Status.RETIRED},
    Status.RETIRED: set(),
}


def validate_transition(
    current: Status | str,
    to: Status | str,
    *,
    approved_by: str | None = None,
) -> None:
    """Validate a requested lifecycle transition.

    Raises:
        InvalidTransitionError: if the transition is not in the allowed map.
        ApprovalRequiredError: if transitioning to 'live' without a non-empty approved_by.
    """
    current_status = Status(current)
    to_status = Status(to)

    allowed = _ALLOWED.get(current_status, set())
    if to_status not in allowed:
        allowed_str = sorted(s.value for s in allowed) or "none"
        raise InvalidTransitionError(
            f"Transition '{current_status}' → '{to_status}' is not permitted. "
            f"Allowed transitions from '{current_status}': {allowed_str}"
        )

    if to_status == Status.LIVE and not approved_by:
        raise ApprovalRequiredError(
            "Transitioning to 'live' requires a non-empty approved_by identifier."
        )

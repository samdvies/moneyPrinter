"""Custom exceptions for the strategy registry."""


class StrategyNotFoundError(Exception):
    """Raised when a strategy ID does not exist in the registry."""


class InvalidTransitionError(Exception):
    """Raised when a requested lifecycle transition is not permitted."""


class ApprovalRequiredError(Exception):
    """Raised when transitioning to 'live' without a non-empty approved_by."""

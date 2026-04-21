"""Custom exceptions for the strategy registry."""


class StrategyNotFoundError(Exception):
    """Raised when a strategy ID does not exist in the registry."""


class InvalidTransitionError(Exception):
    """Raised when a requested lifecycle transition is not permitted."""


class ApprovalRequiredError(Exception):
    """Raised when transitioning to 'live' without a non-empty approved_by."""


class StrategyLoadError(Exception):
    """Raised when a wiki strategy file cannot be parsed or its module is malformed.

    Covers:
      - YAML frontmatter parse failures or missing delimiters.
      - Missing required frontmatter keys.
      - Filename stem / strategy-id mismatch.
      - Module importable but missing a callable ``on_tick`` attribute.

    A truly missing module raises the underlying ``ModuleNotFoundError`` — the
    loader does not swallow it, so callers can distinguish "typo in the dotted
    path" from "the module exists but violates the StrategyModule shape".
    """

"""Custom exceptions for the research orchestrator."""


class OrchestratorError(RuntimeError):
    """Raised when the orchestrator attempts a forbidden lifecycle transition."""

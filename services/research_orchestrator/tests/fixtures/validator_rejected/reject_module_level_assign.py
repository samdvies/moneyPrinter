"""Rejected: assignment at module level (module-level state)."""

DEFAULT_THRESHOLD = 2.0


def compute_signal(snapshot, params):
    threshold = float(params.get("threshold", DEFAULT_THRESHOLD))
    return float(snapshot["price"]) - threshold

"""Rejected: global statement inside a function."""

_state = 0.0


def compute_signal(snapshot, params):
    global _state
    _state += float(snapshot["price"])
    return _state

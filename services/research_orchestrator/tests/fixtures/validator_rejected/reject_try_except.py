"""Rejected: Try/except block."""


def compute_signal(snapshot, params):
    try:
        return float(snapshot["price"])
    except KeyError:
        return None

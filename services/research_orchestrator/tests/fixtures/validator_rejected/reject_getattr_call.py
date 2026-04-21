"""Rejected: call to getattr."""


def compute_signal(snapshot, params):
    val = getattr(snapshot, "price", None)
    return float(val) if val is not None else None

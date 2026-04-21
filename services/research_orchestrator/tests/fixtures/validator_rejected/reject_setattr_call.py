"""Rejected: call to setattr."""


def compute_signal(snapshot, params):
    snapshot.cached = 42
    return float(snapshot["price"])

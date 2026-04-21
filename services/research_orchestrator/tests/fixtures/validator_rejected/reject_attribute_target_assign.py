"""Rejected: assignment to an attribute target (obj.x = value)."""


def compute_signal(snapshot, params):
    snapshot.cached_price = float(snapshot["price"])
    return snapshot.cached_price

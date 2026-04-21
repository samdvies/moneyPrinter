"""Rejected: Assert statement."""


def compute_signal(snapshot, params):
    price = float(snapshot["price"])
    assert price >= 0.0, "price must be non-negative"
    return price

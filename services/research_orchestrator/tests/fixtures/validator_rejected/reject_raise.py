"""Rejected: Raise statement."""


def compute_signal(snapshot, params):
    price = float(snapshot["price"])
    if price < 0.0:
        raise ValueError("negative price")
    return price

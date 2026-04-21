"""Rejected: yield expression (generator function)."""


def compute_signal(snapshot, params):
    price = float(snapshot["price"])
    yield price

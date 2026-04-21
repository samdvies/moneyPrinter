"""Rejected: yield from expression."""


def compute_signal(snapshot, params):
    yield from [float(snapshot["price"])]

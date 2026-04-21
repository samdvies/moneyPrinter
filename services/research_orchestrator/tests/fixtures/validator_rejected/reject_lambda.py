"""Rejected: Lambda expression is not allowed."""


def compute_signal(snapshot, params):
    transform = lambda x: x * 2.0
    return transform(float(snapshot["price"]))

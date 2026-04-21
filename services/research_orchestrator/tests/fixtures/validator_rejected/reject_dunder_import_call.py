"""Rejected: call to __import__."""


def compute_signal(snapshot, params):
    os = __import__("os")
    return float(snapshot["price"])

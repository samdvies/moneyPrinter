"""Rejected: call to exec."""


def compute_signal(snapshot, params):
    exec("x = 1")
    return float(snapshot["price"])

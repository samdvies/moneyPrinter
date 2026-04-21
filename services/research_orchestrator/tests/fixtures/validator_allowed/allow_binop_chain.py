"""Allowed: chained binary operations."""


def compute_signal(snapshot, params):
    a = float(snapshot["a"])
    b = float(snapshot["b"])
    c = float(snapshot["c"])
    result = (a + b - c) * 2.0 / (a + 1.0) ** 0.5 % 10.0
    return result

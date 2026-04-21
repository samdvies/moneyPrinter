"""Rejected: nonlocal statement inside a nested function."""


def compute_signal(snapshot, params):
    acc = 0.0

    def accumulate(val):
        nonlocal acc
        acc += val

    accumulate(float(snapshot["price"]))
    return acc

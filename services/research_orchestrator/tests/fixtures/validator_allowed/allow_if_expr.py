"""Allowed: ternary (if-expression) inside a function body."""


def compute_signal(snapshot, params):
    bid = snapshot["bid"]
    ask = snapshot["ask"]
    mid = (bid + ask) / 2.0
    threshold = float(params["threshold"])
    result = 1.0 if mid > threshold else -1.0 if mid < threshold else None
    return result

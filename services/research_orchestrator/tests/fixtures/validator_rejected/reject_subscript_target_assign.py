"""Rejected: assignment to a subscript target (d[k] = value)."""


def compute_signal(snapshot, params):
    cache = params["cache"]
    cache["last_price"] = float(snapshot["price"])
    return cache["last_price"]

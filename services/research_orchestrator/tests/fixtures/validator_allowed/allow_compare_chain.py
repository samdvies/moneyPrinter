"""Allowed: comparison chains and boolean operators."""


def compute_signal(snapshot, params):
    price = float(snapshot["price"])
    lo = float(params["lo"])
    hi = float(params["hi"])
    if lo <= price <= hi and price > 0.0:
        return price
    if price < lo or price > hi:
        return None
    return 0.0

"""Allowed: is/is not None checks and membership tests (Is, IsNot, In, NotIn)."""


def compute_signal(snapshot, params):
    bid = snapshot.get("best_bid")
    ask = snapshot.get("best_ask")
    if bid is None or ask is None:
        return None
    if "window" not in params:
        return None
    window = params["window"]
    mid = (float(bid) + float(ask)) / 2.0
    if mid is not None and mid > 0.0:
        return mid
    return None

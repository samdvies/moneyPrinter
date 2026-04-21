"""Allowed: subscript reads (dict and list indexing) inside a function."""


def compute_signal(snapshot, params):
    bids = snapshot["bids"]
    asks = snapshot["asks"]
    if not bids or not asks:
        return None
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    mid = (float(best_bid) + float(best_ask)) / 2.0
    window = params["window"]
    last = window[-1] if window else mid
    return mid - last

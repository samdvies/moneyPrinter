"""Allowed: explicit return None and bare return."""


def compute_signal(snapshot, params):
    price = snapshot.get("price")
    if price is None:
        return None
    if float(price) < 0.0:
        return
    return float(price)

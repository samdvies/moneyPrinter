"""Allowed: list literals and list subscript reads."""


def compute_signal(snapshot, params):
    prices = [float(snapshot["p1"]), float(snapshot["p2"]), float(snapshot["p3"])]
    best = min(prices)
    worst = max(prices)
    spread = worst - best
    return spread if spread > float(params["threshold"]) else None

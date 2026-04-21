"""Allowed: dict literal construction inside a function."""


def compute_signal(snapshot, params):
    result = {
        "mid": (float(snapshot["bid"]) + float(snapshot["ask"])) / 2.0,
        "spread": float(snapshot["ask"]) - float(snapshot["bid"]),
    }
    return result["mid"] if result["spread"] < float(params["max_spread"]) else None

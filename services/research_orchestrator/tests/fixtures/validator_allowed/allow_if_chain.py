"""Allowed: if/elif/else chains inside a function."""


def compute_signal(snapshot, params):
    regime = snapshot["regime"]
    threshold = float(params["threshold"])
    price = float(snapshot["price"])
    if regime == "bull":
        signal = price * threshold
    elif regime == "bear":
        signal = -price * threshold
    elif regime == "neutral":
        signal = 0.0
    else:
        return None
    return signal

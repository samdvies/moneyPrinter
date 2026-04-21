"""Allowed: augmented assignment (+=, -=, *=) to Name targets."""


def compute_signal(snapshot, params):
    total = 0.0
    count = 0
    for price in params["window"]:
        total += float(price)
        count += 1
    if count == 0:
        return None
    mean = total / count
    mean *= float(params.get("scale", 1.0))
    return mean

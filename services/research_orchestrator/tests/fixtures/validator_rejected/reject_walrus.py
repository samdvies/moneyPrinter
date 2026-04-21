"""Rejected: walrus operator (:=) — NamedExpr."""


def compute_signal(snapshot, params):
    if (price := float(snapshot["price"])) > 0.0:
        return price
    return None

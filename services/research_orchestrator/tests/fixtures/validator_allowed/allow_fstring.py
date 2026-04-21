"""Allowed: f-string formatting — JoinedStr/FormattedValue nodes are admitted."""


def compute_signal(snapshot, params):
    mid = (float(snapshot["best_bid"]) + float(snapshot["best_ask"])) / 2.0
    label = f"{snapshot['market_id']}:{mid:.4f}"
    if label and mid > 0.0:
        return mid
    return None

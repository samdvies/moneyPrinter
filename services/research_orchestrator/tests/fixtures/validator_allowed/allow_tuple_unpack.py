"""Allowed: tuple unpacking assignment."""


def compute_signal(snapshot, params):
    bid, ask = snapshot["bid"], snapshot["ask"]
    mid = (float(bid) + float(ask)) / 2.0
    lo, hi = float(params["lo"]), float(params["hi"])
    if mid < lo:
        return -1.0
    if mid > hi:
        return 1.0
    return None

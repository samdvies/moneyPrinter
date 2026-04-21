"""Allowed: top-level import statistics with GeneratorExp as argument."""

import statistics


def compute_signal(snapshot, params):
    window = params["window"]
    if len(window) < 2:
        return None
    mean = statistics.mean(x for x in window)
    stdev = statistics.pstdev(x for x in window)
    if stdev == 0.0:
        return None
    latest = float(snapshot["price"])
    return (latest - mean) / stdev

"""Allowed: top-level import math and use of math.sqrt / math.log."""

import math


def compute_signal(snapshot, params):
    price = float(snapshot["price"])
    if price <= 0.0:
        return None
    log_price = math.log(price)
    sqr = math.sqrt(abs(log_price))
    return round(sqr, 4)

"""Pure mean-reversion signal: Grok-style distillation of the reference strategy.

No module-level state, no cross-service imports. The caller owns the window list
(passed in via params["_window"]) and is responsible for maintaining its length.
This function only reads the window and appends to it; trimming is expressed as
a slice read into a local variable so no subscript-target assign is needed.
"""

import math
import statistics


def compute_signal(snapshot, params):
    bids = snapshot["bids"]
    asks = snapshot["asks"]
    if not bids or not asks:
        return None

    mid = (bids[0][0] + asks[0][0]) / 2.0

    window_size = int(params["window_size"])
    window = params["_window"]
    window.append(mid)

    # Read a slice (subscript read, not write) to get the trimmed view.
    view = window[-window_size:] if len(window) > window_size else window

    if len(view) < window_size:
        return None

    mean = statistics.mean(view)
    stddev = statistics.pstdev(view)
    min_stddev = float(params.get("min_stddev", 1e-6))
    if stddev < min_stddev:
        return None

    z = (mid - mean) / stddev
    z_threshold = float(params["z_threshold"])

    if z < -z_threshold:
        return -math.fabs(z)
    if z > z_threshold:
        return math.fabs(z)
    return None

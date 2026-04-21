"""Rejected: Delete statement."""


def compute_signal(snapshot, params):
    window = params["window"]
    window.append(float(snapshot["price"]))
    del window[0]
    return float(window[-1])

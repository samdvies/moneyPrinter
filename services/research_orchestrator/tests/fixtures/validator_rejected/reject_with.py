"""Rejected: With statement (context manager)."""


def compute_signal(snapshot, params):
    with open("/dev/null") as fh:
        fh.read()
    return float(snapshot["price"])

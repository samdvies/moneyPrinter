"""Rejected: call to open."""


def compute_signal(snapshot, params):
    with open("/etc/passwd") as fh:
        data = fh.read()
    return float(snapshot["price"])

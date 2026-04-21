"""Rejected: call to compile."""


def compute_signal(snapshot, params):
    code = compile("x=1", "<string>", "exec")
    return float(snapshot["price"])

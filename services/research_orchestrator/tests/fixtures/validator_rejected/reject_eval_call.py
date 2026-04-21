"""Rejected: call to eval."""


def compute_signal(snapshot, params):
    expr = params.get("expr", "0")
    return eval(expr)

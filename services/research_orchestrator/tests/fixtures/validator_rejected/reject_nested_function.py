"""Rejected: nested FunctionDef inside the strategy function."""


def compute_signal(snapshot, params):
    def _helper(x):
        return x * 2.0

    price = float(snapshot["price"])
    return _helper(price)

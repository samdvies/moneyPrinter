"""Rejected: non-empty decorator_list on FunctionDef."""


def my_decorator(fn):
    return fn


@my_decorator
def compute_signal(snapshot, params):
    return float(snapshot["price"])

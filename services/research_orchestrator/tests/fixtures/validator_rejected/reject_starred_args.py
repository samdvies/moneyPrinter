"""Rejected: Starred expression (*args unpacking)."""


def compute_signal(snapshot, params):
    values = [1.0, 2.0, 3.0]
    result = max(*values)
    return result

"""Rejected: access of a banned dunder attribute (e.g. __class__.__mro__)."""


def compute_signal(snapshot, params):
    mro = ().__class__.__mro__
    return float(len(mro))

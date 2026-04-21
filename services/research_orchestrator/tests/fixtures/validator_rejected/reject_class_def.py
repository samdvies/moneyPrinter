"""Rejected: ClassDef at module or function level."""


class Signal:
    def __init__(self, value):
        self.value = value


def compute_signal(snapshot, params):
    return Signal(float(snapshot["price"])).value

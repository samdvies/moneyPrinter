"""Rejected: comprehension whose elt/value calls a banned function (open)."""


def compute_signal(snapshot, params):
    paths = params.get("paths", [])
    contents = [open(p).read() for p in paths]
    return float(len(contents))

"""Rejected: try* (ExceptionGroup / TryStar) — Python 3.11+ syntax."""


def compute_signal(snapshot, params):
    try:
        return float(snapshot["price"])
    except* ValueError as eg:
        return None

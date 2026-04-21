"""Rejected: match statement — Python 3.10+ structural pattern matching."""


def compute_signal(snapshot, params):
    match snapshot.get("signal_type"):
        case "buy":
            return 1.0
        case "sell":
            return -1.0
        case _:
            return None

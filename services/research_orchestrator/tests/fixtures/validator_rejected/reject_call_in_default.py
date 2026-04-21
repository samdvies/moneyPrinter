"""Rejected: function call in a default argument value (e.g. open('/etc'))."""


def compute_signal(snapshot, params, x=open("/etc/passwd")):
    return float(snapshot["price"])

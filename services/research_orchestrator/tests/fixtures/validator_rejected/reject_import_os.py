"""Rejected: import of a non-whitelisted module (os)."""
import os


def compute_signal(snapshot, params):
    return float(snapshot["price"])

"""Rejected: from-import (ImportFrom) is never allowed."""

from math import sqrt


def compute_signal(snapshot, params):
    return sqrt(float(snapshot["price"]))

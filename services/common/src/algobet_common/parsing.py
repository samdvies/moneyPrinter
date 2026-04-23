"""Shared parsing helpers for venue adapter payloads."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def parse_decimal(value: Any) -> Decimal | None:
    """Parse a venue-supplied price/size into Decimal, or None on failure."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None

"""Kalshi market-data payload mapping helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from algobet_common.parsing import parse_decimal
from algobet_common.schemas import MarketData, Venue


def _parse_timestamp(payload: dict[str, Any]) -> datetime:
    raw_timestamp = payload.get("ts") or payload.get("timestamp")
    if isinstance(raw_timestamp, int | float):
        # Kalshi feeds commonly provide epoch milliseconds.
        if raw_timestamp > 10_000_000_000:
            return datetime.fromtimestamp(raw_timestamp / 1000, tz=UTC)
        return datetime.fromtimestamp(raw_timestamp, tz=UTC)
    if isinstance(raw_timestamp, str):
        parsed = raw_timestamp.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(parsed)
        except ValueError:
            return datetime.now(UTC)
    return datetime.now(UTC)


def _normalize_ladder(levels: Any) -> list[tuple[Decimal, Decimal]]:
    if not isinstance(levels, list):
        return []

    normalized: list[tuple[Decimal, Decimal]] = []
    for level in levels:
        if not isinstance(level, dict):
            continue
        price = parse_decimal(level.get("price"))
        size = parse_decimal(level.get("size"))
        if price is None or size is None:
            continue
        normalized.append((price, size))
    return normalized


def kalshi_message_to_market_data(payload: dict[str, Any]) -> MarketData | None:
    """Map a Kalshi WebSocket payload into internal MarketData.

    Returns None when required fields are missing or malformed.
    """
    market_ticker = payload.get("market_ticker") or payload.get("market_id")
    if not isinstance(market_ticker, str) or not market_ticker:
        return None

    bids = _normalize_ladder(payload.get("bids"))
    asks = _normalize_ladder(payload.get("asks"))
    last_trade = None
    for key in ("last_trade", "last_trade_price", "last_price", "price"):
        last_trade = parse_decimal(payload.get(key))
        if last_trade is not None:
            break

    return MarketData(
        venue=Venue.KALSHI,
        market_id=market_ticker,
        timestamp=_parse_timestamp(payload),
        bids=bids,
        asks=asks,
        last_trade=last_trade,
    )

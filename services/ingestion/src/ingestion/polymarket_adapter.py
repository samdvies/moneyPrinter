"""Polymarket market-data ingestion adapter (read-only).

Polls the public Gamma REST endpoint for all currently-active Polymarket
markets and publishes `MarketData` messages to the Redis Streams bus. One
message is emitted per CLOB `token_id` so that a future trading adapter
can address markets by `market_id` without schema translation.

Tier 0 public reads only — no API key, no Polygon wallet, no USDC. Order
placement is intentionally out of scope; see `scripts/polymarket_*_probe.py`
for the throwaway auth/order experiments.

Requires the operator's outbound traffic to exit from a country that is
not on Polymarket's restricted list. The adapter refuses to start if
`ipinfo.io/json` reports `GB` or `US`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from algobet_common.bus import BusClient, Topic
from algobet_common.parsing import parse_decimal
from algobet_common.schemas import MarketData, Venue

LOGGER = logging.getLogger(__name__)

_BLOCKED_EGRESS_COUNTRIES = frozenset({"GB", "US"})
_EGRESS_URL = "https://ipinfo.io/json"
_MARKETS_PATH = "/markets"
_EGRESS_RECHECK_INTERVAL_CYCLES = 12


class PolymarketEgressError(RuntimeError):
    """Raised when outbound IP is in a Polymarket-blocked country."""


def _parse_json_string_list(raw: Any) -> list[Any]:
    """Gamma encodes `clobTokenIds` and `outcomePrices` as JSON strings."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return list(parsed) if isinstance(parsed, list) else []
    return []


def gamma_market_to_market_data(
    payload: dict[str, Any],
    *,
    timestamp: datetime | None = None,
) -> list[MarketData]:
    """Map one Gamma market object into per-outcome `MarketData` messages.

    Gamma's `bestBid` / `bestAsk` / `lastTradePrice` refer to the YES token
    (`clobTokenIds[0]`). For NO we only have `outcomePrices[1]` as an
    implied last-trade; real NO bid/ask requires a CLOB `/book` call and
    is out of scope for the MVP fan-out. Size on the YES ladder is emitted
    as `Decimal("0")` — a "depth unknown" sentinel for downstream
    consumers that filter on `size > 0`.
    """
    token_ids = [str(t) for t in _parse_json_string_list(payload.get("clobTokenIds")) if t]
    if not token_ids:
        return []

    outcome_prices = [
        parse_decimal(p) for p in _parse_json_string_list(payload.get("outcomePrices"))
    ]
    best_bid = parse_decimal(payload.get("bestBid"))
    best_ask = parse_decimal(payload.get("bestAsk"))
    last_trade_yes = parse_decimal(payload.get("lastTradePrice"))
    ts = timestamp or datetime.now(UTC)

    messages: list[MarketData] = []
    for idx, token_id in enumerate(token_ids):
        if idx == 0:
            bids = [(best_bid, Decimal("0"))] if best_bid is not None else []
            asks = [(best_ask, Decimal("0"))] if best_ask is not None else []
            trade = last_trade_yes
        else:
            bids = []
            asks = []
            trade = outcome_prices[idx] if idx < len(outcome_prices) else None
        messages.append(
            MarketData(
                venue=Venue.POLYMARKET,
                market_id=token_id,
                timestamp=ts,
                bids=bids,
                asks=asks,
                last_trade=trade,
            )
        )
    return messages


async def check_egress_country(client: httpx.AsyncClient) -> str:
    """Return the ISO country code of the current egress, or raise."""
    resp = await client.get(_EGRESS_URL, timeout=10.0)
    resp.raise_for_status()
    country = str(resp.json().get("country", "")).upper()
    if not country:
        raise PolymarketEgressError("egress country could not be determined")
    if country in _BLOCKED_EGRESS_COUNTRIES:
        raise PolymarketEgressError(
            f"outbound egress is {country}; Polymarket adapter refuses to run "
            f"from a blocked country. Activate VPN to a non-restricted region."
        )
    return country


async def fetch_active_markets_page(
    client: httpx.AsyncClient,
    *,
    gamma_base_url: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """Return one page of active markets from Gamma."""
    resp = await client.get(
        f"{gamma_base_url.rstrip('/')}{_MARKETS_PATH}",
        params={"closed": "false", "limit": limit, "offset": offset},
        timeout=15.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    return list(payload) if isinstance(payload, list) else []


async def publish_gamma_markets(
    bus: BusClient,
    markets: Iterable[dict[str, Any]],
    *,
    timestamp: datetime | None = None,
) -> int:
    """Map and publish MarketData messages for a batch of Gamma markets."""
    published = 0
    for market in markets:
        for message in gamma_market_to_market_data(market, timestamp=timestamp):
            await bus.publish(Topic.MARKET_DATA, message)
            published += 1
    return published


async def run_polymarket_poll_loop(
    *,
    bus: BusClient,
    gamma_base_url: str,
    poll_interval_seconds: float,
    page_size: int,
    http_client: httpx.AsyncClient | None = None,
    max_cycles: int | None = None,
) -> int:
    """Continuously poll Gamma for active markets and publish to Redis.

    Fails closed if the egress country is blocked. Logs and backs off on
    transient HTTP errors; re-checks egress every few cycles so a mid-run
    VPN drop stops the adapter within about a minute.
    """
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient()
    total_published = 0
    try:
        cycle = 0
        while max_cycles is None or cycle < max_cycles:
            if cycle % _EGRESS_RECHECK_INTERVAL_CYCLES == 0:
                try:
                    await check_egress_country(client)
                except PolymarketEgressError:
                    LOGGER.exception("polymarket egress guard failed; aborting loop")
                    raise
            cycle += 1

            offset = 0
            cycle_published = 0
            while True:
                try:
                    page = await fetch_active_markets_page(
                        client,
                        gamma_base_url=gamma_base_url,
                        limit=page_size,
                        offset=offset,
                    )
                except httpx.HTTPError:
                    LOGGER.exception(
                        "polymarket gamma page fetch failed at offset=%s; will retry next cycle",
                        offset,
                    )
                    break
                if not page:
                    break
                cycle_published += await publish_gamma_markets(bus, page)
                if len(page) < page_size:
                    break
                offset += page_size

            total_published += cycle_published
            LOGGER.info(
                "polymarket cycle %s published %s messages (total %s)",
                cycle,
                cycle_published,
                total_published,
            )
            await asyncio.sleep(poll_interval_seconds)
    finally:
        if owns_client:
            await client.aclose()
    return total_published

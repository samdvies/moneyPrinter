"""Betfair stream adapter helpers for ingestion service."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from algobet_common.bus import BusClient, Topic
from algobet_common.schemas import MarketData, Venue

LOGGER = logging.getLogger(__name__)

_DEFAULT_MARKET_FIELDS = ("EX_BEST_OFFERS", "EX_LTP")
_DEFAULT_LADDER_LEVELS = 10


class IngestionCredentialsError(ValueError):
    """Raised when required Betfair credentials are not configured."""


def require_betfair_credentials(
    *, username: str, password: str, app_key: str, certs_dir: str
) -> None:
    """Validate non-empty Betfair credential values."""
    missing = []
    if not username:
        missing.append("BETFAIR_USERNAME")
    if not password:
        missing.append("BETFAIR_PASSWORD")
    if not app_key:
        missing.append("BETFAIR_APP_KEY")
    if not certs_dir:
        missing.append("BETFAIR_CERTS_DIR")
    if missing:
        missing_fields = ", ".join(missing)
        raise IngestionCredentialsError(
            "Missing Betfair ingestion credentials/config: "
            f"{missing_fields}. Provide them via environment variables."
        )


def _normalize_ladder(price_sizes: Sequence[Any]) -> list[tuple[Decimal, Decimal]]:
    normalized: list[tuple[Decimal, Decimal]] = []
    for row in price_sizes:
        price = getattr(row, "price", None)
        size = getattr(row, "size", None)
        if price is None or size is None:
            continue
        normalized.append((Decimal(str(price)), Decimal(str(size))))
    return normalized


def _timestamp_from_publish_time(
    publish_time_ms: int | None, fallback_timestamp: datetime | None
) -> datetime:
    if publish_time_ms is not None:
        return datetime.fromtimestamp(publish_time_ms / 1000, tz=UTC)
    if fallback_timestamp is not None:
        return fallback_timestamp
    return datetime.now(UTC)


def map_market_book_to_messages(
    market_book: Any, *, fallback_timestamp: datetime | None = None
) -> list[MarketData]:
    """Map a Betfair market book update into per-runner MarketData messages."""
    timestamp = _timestamp_from_publish_time(
        publish_time_ms=getattr(market_book, "publish_time", None),
        fallback_timestamp=fallback_timestamp,
    )
    market_id = str(market_book.market_id)
    messages: list[MarketData] = []
    for runner in getattr(market_book, "runners", []):
        exchange = getattr(runner, "ex", None)
        if exchange is None:
            continue
        bids = _normalize_ladder(getattr(exchange, "available_to_back", []))
        asks = _normalize_ladder(getattr(exchange, "available_to_lay", []))
        last_price = getattr(runner, "last_price_traded", None)
        last_trade = Decimal(str(last_price)) if last_price is not None else None
        selection_id = str(runner.selection_id)
        messages.append(
            MarketData(
                venue=Venue.BETFAIR,
                market_id=f"{market_id}:{selection_id}",
                timestamp=timestamp,
                bids=bids,
                asks=asks,
                last_trade=last_trade,
            )
        )
    return messages


async def publish_market_books(bus: BusClient, market_books: Sequence[Any]) -> int:
    """Publish all MarketData messages derived from market books."""
    published = 0
    for market_book in market_books:
        for message in map_market_book_to_messages(market_book):
            await bus.publish(Topic.MARKET_DATA, message)
            published += 1
    return published


def create_betfair_client(*, username: str, password: str, app_key: str, certs_dir: str) -> Any:
    """Create Betfair API client."""
    import betfairlightweight

    return betfairlightweight.APIClient(
        username=username,
        password=password,
        app_key=app_key,
        certs=certs_dir,
    )


def create_market_stream(
    client: Any,
    *,
    market_ids: Sequence[str],
    conflate_ms: int,
    market_fields: Sequence[str] = _DEFAULT_MARKET_FIELDS,
    ladder_levels: int = _DEFAULT_LADDER_LEVELS,
) -> Any:
    """Create and subscribe a Betfair market stream."""
    import betfairlightweight

    listener = betfairlightweight.StreamListener(max_latency=None)
    stream = client.streaming.create_stream(listener=listener)
    stream.subscribe_to_markets(
        market_filter={"marketIds": list(market_ids)},
        market_data_filter={"fields": list(market_fields), "ladderLevels": ladder_levels},
        conflate_ms=conflate_ms,
    )
    return stream


async def consume_stream_updates(
    *,
    stream: Any,
    bus: BusClient,
    poll_interval_seconds: float,
    max_batches: int | None = None,
) -> int:
    """Read updates from a Betfair stream and publish mapped market data."""
    stream.start()
    get_updates = stream.get_generator()
    published = 0
    batch_count = 0
    try:
        while max_batches is None or batch_count < max_batches:
            market_books = get_updates()
            batch_count += 1
            if not market_books:
                await asyncio.sleep(poll_interval_seconds)
                continue
            published += await publish_market_books(bus=bus, market_books=market_books)
    finally:
        stop = getattr(stream, "stop", None)
        if callable(stop):
            stop()
    return published


async def run_betfair_stream_loop(
    *,
    bus: BusClient,
    username: str,
    password: str,
    app_key: str,
    certs_dir: str,
    market_ids: Sequence[str],
    conflate_ms: int,
    reconnect_delay_seconds: float,
    poll_interval_seconds: float,
) -> None:
    """Continuously stream Betfair market data and publish to Redis."""
    require_betfair_credentials(
        username=username,
        password=password,
        app_key=app_key,
        certs_dir=certs_dir,
    )
    if not market_ids:
        raise IngestionCredentialsError(
            "Missing BETFAIR_MARKET_IDS. Configure at least one market id."
        )

    while True:
        client = create_betfair_client(
            username=username,
            password=password,
            app_key=app_key,
            certs_dir=certs_dir,
        )
        try:
            client.login()
            stream = create_market_stream(
                client=client,
                market_ids=market_ids,
                conflate_ms=conflate_ms,
            )
            published = await consume_stream_updates(
                stream=stream,
                bus=bus,
                poll_interval_seconds=poll_interval_seconds,
            )
            LOGGER.info("betfair stream loop ended after publishing %s messages", published)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("betfair stream failed; retrying after backoff")
            await asyncio.sleep(reconnect_delay_seconds)
        finally:
            logout = getattr(client, "logout", None)
            if callable(logout):
                try:
                    logout()
                except Exception:
                    LOGGER.exception("failed to logout betfair client cleanly")

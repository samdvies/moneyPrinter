"""Pure deterministic fill engine.

No randomness, no latency modelling. Fills are crossed against the best
available price levels in the order book.

BACK / YES: taker hits asks (best ask first, ascending price).
LAY  / NO:  taker hits bids (best bid first, descending price).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from algobet_common.schemas import ExecutionResult, MarketData, OrderSide, OrderSignal

_TAKER_SIDES: frozenset[OrderSide] = frozenset({OrderSide.BACK, OrderSide.YES})
_MAKER_SIDES: frozenset[OrderSide] = frozenset({OrderSide.LAY, OrderSide.NO})


def _vwap(fills: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Volume-weighted average price from a list of (price, size) fill pairs."""
    total_size = sum(s for _, s in fills)
    if total_size == Decimal("0"):
        return Decimal("0")
    return sum(p * s for p, s in fills) / total_size


def _walk_ladder(
    stake: Decimal,
    levels: list[tuple[Decimal, Decimal]],
    crosses: "callable[[Decimal], bool]",
) -> tuple[Decimal, Decimal | None, Literal["placed", "partially_filled", "filled"]]:
    """Walk price levels, consuming stake until exhausted or no crossing level.

    Returns (filled_stake, filled_price_or_None, status).
    """
    remaining = stake
    fills: list[tuple[Decimal, Decimal]] = []

    for price, size in levels:
        if size <= Decimal("0"):
            continue
        if not crosses(price):
            break
        take = min(remaining, size)
        fills.append((price, take))
        remaining -= take
        if remaining <= Decimal("0"):
            break

    filled_stake = stake - remaining
    if filled_stake <= Decimal("0"):
        return Decimal("0"), None, "placed"
    filled_price = _vwap(fills)
    if remaining <= Decimal("0"):
        return filled_stake, filled_price, "filled"
    return filled_stake, filled_price, "partially_filled"


def match_order(signal: OrderSignal, book: MarketData) -> ExecutionResult:
    """Match an order signal against a market data snapshot.

    Returns an ExecutionResult with status, filled_stake, and filled_price.
    The order_id is freshly generated (UUID4).
    """
    if signal.side in _TAKER_SIDES:
        # BACK / YES: cross against asks (ascending), fill if ask.price <= signal.price
        levels = sorted(book.asks, key=lambda x: x[0])
        filled_stake, filled_price, status = _walk_ladder(
            signal.stake,
            levels,
            crosses=lambda ask_price: ask_price <= signal.price,
        )
    else:
        # LAY / NO: cross against bids (descending), fill if bid.price >= signal.price
        levels = sorted(book.bids, key=lambda x: x[0], reverse=True)
        filled_stake, filled_price, status = _walk_ladder(
            signal.stake,
            levels,
            crosses=lambda bid_price: bid_price >= signal.price,
        )

    return ExecutionResult(
        order_id=str(uuid.uuid4()),
        strategy_id=signal.strategy_id,
        mode=signal.mode,
        status=status,
        filled_stake=filled_stake,
        filled_price=filled_price,
        timestamp=datetime.now(UTC),
    )

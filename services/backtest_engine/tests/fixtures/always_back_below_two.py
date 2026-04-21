"""Trivial BACK-only strategy used by the determinism pin in test_harness.

Emits a BACK signal whenever the best ask is <= 1.50. The strategy is a
module with an ``on_tick`` function — the harness ``StrategyModule`` Protocol
is structural, so passing the module directly satisfies the contract.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from algobet_common.schemas import MarketData, OrderSide, OrderSignal, Venue

# All-zero UUID is fine here — the harness never validates strategy_id on
# the signal, and the fixture intentionally avoids touching the DB.
_FIXTURE_STRATEGY_ID = "00000000-0000-0000-0000-000000000000"
_THRESHOLD = Decimal("1.50")


def on_tick(
    snapshot: MarketData,
    params: dict[str, Any],
    now: datetime,
) -> OrderSignal | None:
    """Return a BACK signal when best ask <= 1.50, else None."""
    if not snapshot.asks:
        return None
    best_ask_price = snapshot.asks[0][0]
    if best_ask_price > _THRESHOLD:
        return None
    stake = params.get("stake", Decimal("10"))
    return OrderSignal(
        strategy_id=_FIXTURE_STRATEGY_ID,
        mode="paper",
        venue=snapshot.venue if isinstance(snapshot.venue, Venue) else Venue(snapshot.venue),
        market_id=snapshot.market_id,
        side=OrderSide.BACK,
        stake=stake,
        price=best_ask_price,
    )

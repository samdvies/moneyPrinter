"""Trivial BACK-only strategy — production home for the 6a reference fixture.

Emits a BACK signal whenever the best ask is <= 1.50. The module satisfies
the structural ``StrategyModule`` Protocol by exposing a module-level
``on_tick`` callable.

This lives in ``src/`` (not ``tests/fixtures/``) so the research orchestrator
can import it for its synthetic smoke loop without depending on test code.
Phase 6b will replace the orchestrator's use of this with a research-generated
strategy; the module stays around as a reference artefact and as the
determinism-test fixture re-export target.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from algobet_common.schemas import MarketData, OrderSide, OrderSignal, Venue

# All-zero UUID is a stand-in: the harness never validates strategy_id on
# the signal, and this module is intentionally DB-free. Callers that do
# want a real registry row (the orchestrator) pass ``strategy_id`` to the
# harness itself; the signal's ``strategy_id`` is informational.
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

"""Constant-stake mean-reversion reference strategy (Phase 6b).

Maintains a rolling window of the last ``window_size`` mid-prices via a
``_window`` list tucked into ``params`` (the explicit state channel — no
module-level globals, preserving the purity invariant enforced by Phase 6c's
AST walk). When the current mid deviates more than ``z_threshold`` standard
deviations below the window mean, emit a BACK at best_ask; above
``+z_threshold``, emit a LAY at best_bid. Otherwise no signal.

Position sizing is constant (``stake_gbp``); exits are implicit — the
opposite-side signal closes the prior position (harness settlement, not this
module's concern).

This module is venue-agnostic: it touches only ``bids[0]`` / ``asks[0]``
and always emits BACK/LAY constants. ``params["venue"]`` is informational
routing metadata, not a behavioural switch.

Caller must not share ``params`` across strategy instances; ``params['_window']``
is per-instance mutable state.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from decimal import Decimal
from typing import Any

from algobet_common.schemas import MarketData, OrderSide, OrderSignal, Venue

# Same all-zero UUID stand-in as ``trivial``: the signal's ``strategy_id`` is
# informational. Real registry-row IDs are threaded through the harness, not
# this pure module.
_FIXTURE_STRATEGY_ID = "00000000-0000-0000-0000-000000000000"


def on_tick(
    snapshot: MarketData,
    params: dict[str, Any],
    _now: datetime,
) -> OrderSignal | None:
    """Emit a BACK/LAY signal when mid-price z-score exceeds threshold."""
    if not snapshot.bids or not snapshot.asks:
        return None

    best_bid_price = snapshot.bids[0][0]
    best_ask_price = snapshot.asks[0][0]
    mid = (best_bid_price + best_ask_price) / Decimal(2)

    window_size = int(params["window_size"])
    window: list[Decimal] = params.setdefault("_window", [])
    window.append(mid)
    if len(window) > window_size:
        del window[0 : len(window) - window_size]

    if len(window) < window_size:
        return None

    # Compute mean in Decimal, then coerce to float for stddev + z arithmetic.
    # Stakes/prices are rebuilt as Decimal at the signal boundary.
    mean_d = sum(window, Decimal(0)) / Decimal(len(window))
    stddev = statistics.pstdev(float(x) for x in window)
    # Guards against near-constant windows where fp noise would inflate z arbitrarily.
    min_stddev = float(params.get("min_stddev", 1e-6))
    if stddev < min_stddev:
        return None

    z = (float(mid) - float(mean_d)) / stddev
    z_threshold = float(params["z_threshold"])
    stake = Decimal(str(params["stake_gbp"]))
    venue = snapshot.venue if isinstance(snapshot.venue, Venue) else Venue(snapshot.venue)

    if z < -z_threshold:
        return OrderSignal(
            strategy_id=_FIXTURE_STRATEGY_ID,
            mode="paper",
            venue=venue,
            market_id=snapshot.market_id,
            side=OrderSide.BACK,
            stake=stake,
            price=best_ask_price,
        )
    if z > z_threshold:
        return OrderSignal(
            strategy_id=_FIXTURE_STRATEGY_ID,
            mode="paper",
            venue=venue,
            market_id=snapshot.market_id,
            side=OrderSide.LAY,
            stake=stake,
            price=best_bid_price,
        )
    return None

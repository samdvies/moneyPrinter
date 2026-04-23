"""Live strategy dispatch loop.

Consumes `market.data`, filters ticks by each registered strategy's declared
venue, invokes the strategy's `on_tick(snapshot, params, now)` with per-
`(strategy_id, market_id)` mutable state, and publishes any returned
`OrderSignal` to `order.signals` in `mode="paper"`.

This is the first service in the project that emits signals to the bus —
upstream was blank. Paper-trading wiring:

    ingestion -> market.data -> strategy_runner -> order.signals
                                                -> risk_manager (audit)
                                                -> simulator -> execution.results
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from algobet_common.bus import BusClient, Topic
from algobet_common.schemas import MarketData, OrderSignal, Venue

LOGGER = logging.getLogger(__name__)

StrategyCallable = Callable[[MarketData, dict[str, Any], datetime], OrderSignal | None]


@dataclass
class RegisteredStrategy:
    strategy_id: str
    slug: str
    venue: Venue
    on_tick: StrategyCallable
    base_params: dict[str, Any] = field(default_factory=dict)


async def run_strategy_runner_loop(
    *,
    bus: BusClient,
    strategies: list[RegisteredStrategy],
    max_ticks: int | None = None,
) -> int:
    if not strategies:
        raise ValueError("strategy_runner requires at least one registered strategy")
    state: dict[tuple[str, str], dict[str, Any]] = {}
    ticks_processed = 0
    signals_published = 0
    keep_running = True
    while keep_running:
        async for tick in bus.consume(Topic.MARKET_DATA, MarketData, block_ms=1000):
            ticks_processed += 1
            for strategy in strategies:
                if tick.venue != strategy.venue:
                    continue
                key = (strategy.strategy_id, tick.market_id)
                params = state.setdefault(key, {**strategy.base_params})
                signal = strategy.on_tick(tick, params, tick.timestamp)
                if signal is None:
                    continue
                signal = signal.model_copy(
                    update={"strategy_id": strategy.strategy_id, "mode": "paper"}
                )
                await bus.publish(Topic.ORDER_SIGNALS, signal)
                signals_published += 1
                LOGGER.info(
                    "strategy=%s venue=%s market=%s side=%s stake=%s price=%s",
                    strategy.slug,
                    signal.venue,
                    signal.market_id,
                    signal.side,
                    signal.stake,
                    signal.price,
                )
            if max_ticks is not None and ticks_processed >= max_ticks:
                keep_running = False
                break
    return signals_published

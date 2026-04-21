"""Backtest harness — wires tick sources, the fill engine, and metrics.

Dual-mode ``run_backtest``:

- With ``db`` + ``strategy_id`` supplied, the harness creates a
  ``strategy_runs`` row via ``crud.start_run`` before replay and seals it
  with ``crud.end_run`` (metrics populated, ``ended_at`` set) after the run
  completes. This is the mode the research orchestrator uses in production.
- With either argument omitted, DB writes are skipped entirely. This is the
  mode unit tests use — the determinism pin does not need a database.

The contract is documented in
``docs/superpowers/plans/2026-04-20-phase6a-backtest-harness.md`` and must be
preserved because 6a.4 (orchestrator rewire) consumes it verbatim.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypedDict

from algobet_common.db import Database
from algobet_common.schemas import ExecutionResult
from simulator.book import Book
from simulator.fills import match_order
from strategy_registry import crud
from strategy_registry.models import Mode

from backtest_engine.metrics import (
    max_drawdown_gbp,
    sharpe,
    total_pnl_gbp,
    trivial_settlement,
    win_rate,
)
from backtest_engine.strategy_protocol import StrategyModule, TickSource


class BacktestResult(TypedDict):
    """Fixed-shape dict matching the ``strategy_runs.metrics`` jsonb column.

    Every key must remain JSON-serialisable via ``json.dumps(default=str)``
    (the pattern used by ``strategy_registry.crud.end_run``). Decimals
    serialise to strings, datetimes to ISO 8601.
    """

    sharpe: float
    total_pnl_gbp: Decimal
    max_drawdown_gbp: Decimal
    n_trades: int
    win_rate: float
    n_ticks_consumed: int
    started_at: datetime
    ended_at: datetime


async def run_backtest(
    strategy: StrategyModule,
    params: dict[str, Any],
    source: TickSource,
    time_range: tuple[datetime, datetime],
    *,
    db: Database | None = None,
    strategy_id: uuid.UUID | None = None,
    starting_bankroll_gbp: Decimal = Decimal("1000"),
) -> BacktestResult:
    """Replay ``source`` through ``strategy`` and return a metrics dict.

    When both ``db`` and ``strategy_id`` are supplied, the harness bookends
    the replay with ``crud.start_run(mode='backtest')`` / ``crud.end_run``
    so the run is observable in the strategy registry. When either is None,
    DB writes are skipped — tests use this mode.

    ``starting_bankroll_gbp`` is threaded through for 6b's real settlement;
    6a's trivial settlement ignores it.
    """
    del starting_bankroll_gbp  # reserved for 6b real settlement

    started_at = datetime.now(UTC)

    run_id: uuid.UUID | None = None
    if db is not None and strategy_id is not None:
        run = await crud.start_run(db, strategy_id, Mode.BACKTEST)
        run_id = run.id

    book = Book()
    fills: list[ExecutionResult] = []
    per_tick_pnl: list[Decimal] = []
    equity_curve: list[Decimal] = []
    running_pnl = Decimal("0")
    n_ticks = 0

    async for tick in source.iter_ticks(time_range):
        n_ticks += 1
        book.update(tick)
        tick_timestamp = tick.timestamp
        signal = strategy.on_tick(tick, params, tick_timestamp)

        tick_pnl = Decimal("0")
        if signal is not None:

            def _tick_clock(ts: datetime = tick_timestamp) -> datetime:
                return ts

            result = match_order(signal, tick, now_fn=_tick_clock)
            fills.append(result)
            if result.filled_stake > Decimal("0"):
                tick_pnl = trivial_settlement(result)

        running_pnl += tick_pnl
        per_tick_pnl.append(tick_pnl)
        equity_curve.append(running_pnl)

    ended_at = datetime.now(UTC)

    result_dict: BacktestResult = {
        "sharpe": sharpe(per_tick_pnl),
        "total_pnl_gbp": total_pnl_gbp(fills, trivial_settlement),
        "max_drawdown_gbp": max_drawdown_gbp(equity_curve),
        "n_trades": sum(1 for f in fills if f.filled_stake > Decimal("0")),
        "win_rate": win_rate(fills),
        "n_ticks_consumed": n_ticks,
        "started_at": started_at,
        "ended_at": ended_at,
    }

    if db is not None and run_id is not None:
        await crud.end_run(db, run_id, metrics=_jsonable(result_dict))

    return result_dict


def _jsonable(result: BacktestResult) -> dict[str, Any]:
    """Coerce the BacktestResult into a jsonb-safe dict for persistence.

    ``crud.end_run`` calls ``json.dumps(metrics)`` — Decimals and datetimes
    are not natively JSON-serialisable, so we stringify them here. This
    mirrors the pattern already used throughout strategy_registry.
    """
    return {
        "sharpe": result["sharpe"],
        "total_pnl_gbp": str(result["total_pnl_gbp"]),
        "max_drawdown_gbp": str(result["max_drawdown_gbp"]),
        "n_trades": result["n_trades"],
        "win_rate": result["win_rate"],
        "n_ticks_consumed": result["n_ticks_consumed"],
        "started_at": result["started_at"].isoformat(),
        "ended_at": result["ended_at"].isoformat(),
    }

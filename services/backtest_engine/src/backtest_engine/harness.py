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

NOTE on types vs JSONB:
    ``BacktestResult`` is a ``TypedDict`` of native Python values —
    ``Decimal`` for monetary precision (``total_pnl_gbp``,
    ``max_drawdown_gbp``) and ``datetime`` for the run bookends
    (``started_at``, ``ended_at``). Phase 6b/6c callers that consume the
    result programmatically (orchestrator evaluation, dashboard rendering)
    keep these rich types. Only the DB write path is coerced: the private
    ``_jsonable`` helper is the single JSONB boundary — it stringifies
    Decimals and ISO-formats datetimes so ``crud.end_run`` can write the
    dict into ``strategy_runs.metrics`` via ``json.dumps`` without each
    caller having to repeat the coercion.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypedDict

from algobet_common.db import Database
from algobet_common.schemas import ExecutionResult
from simulator.book import Book
from simulator.fills import match_order
from strategy_registry import crud
from strategy_registry.models import Mode

from backtest_engine.harness_metrics import (
    build_delta_pnl_settlement,
    max_drawdown_gbp,
    sharpe,
    total_pnl_gbp_from_pnls,
    win_rate_from_pnls,
)
from backtest_engine.strategy_protocol import StrategyModule, TickSource


class BacktestResult(TypedDict):
    """Fixed-shape dict matching the ``strategy_runs.metrics`` jsonb column.

    Fields hold native Python types (``Decimal``, ``datetime``). The
    ``_jsonable`` helper is responsible for the JSONB boundary coercion
    — see the module docstring.
    """

    sharpe: float
    total_pnl_gbp: Decimal
    max_drawdown_gbp: Decimal
    n_trades: int
    win_rate: float
    n_ticks_consumed: int
    started_at: datetime
    ended_at: datetime


def _default_now() -> datetime:
    """Wall-clock factory used as the default ``clock`` for ``run_backtest``.

    Factored out so the determinism test can inject a fixed-sequence clock
    and assert structural equality on every key of the ``BacktestResult``.
    """
    return datetime.now(UTC)


async def run_backtest(
    strategy: StrategyModule,
    params: dict[str, Any],
    source: TickSource,
    time_range: tuple[datetime, datetime],
    *,
    db: Database | None = None,
    strategy_id: uuid.UUID | None = None,
    starting_bankroll_gbp: Decimal = Decimal("1000"),
    clock: Callable[[], datetime] = _default_now,
) -> BacktestResult:
    """Replay ``source`` through ``strategy`` and return a metrics dict.

    When both ``db`` and ``strategy_id`` are supplied, the harness bookends
    the replay with ``crud.start_run(mode='backtest')`` / ``crud.end_run``
    so the run is observable in the strategy registry. When either is None,
    DB writes are skipped — tests use this mode.

    ``starting_bankroll_gbp`` is threaded through for 6b's real settlement;
    6a's trivial settlement ignores it.

    ``clock`` is the time source for ``started_at`` / ``ended_at``. The
    default is wall-clock ``datetime.now(UTC)``; the determinism test
    injects a fixed clock so every key of the result dict (including the
    bookend timestamps) is bit-identical across replays.
    """
    del starting_bankroll_gbp  # reserved for future settlement enrichment

    started_at = clock()

    run_id: uuid.UUID | None = None
    if db is not None and strategy_id is not None:
        run = await crud.start_run(db, strategy_id, Mode.BACKTEST)
        run_id = run.id

    book = Book()
    # Per-fill log: (ExecutionResult, realised_pnl). The realised P&L comes
    # from a single stateful settlement closure instantiated per run, so the
    # equity curve and the terminal total both consult one source of truth.
    fill_log: list[tuple[ExecutionResult, Decimal]] = []
    per_tick_pnl: list[Decimal] = []
    equity_curve: list[Decimal] = []
    running_pnl = Decimal("0")
    settlement = build_delta_pnl_settlement()
    # ``ticks_seen`` is updated *before* ``strategy.on_tick`` so that a mid-tick
    # raise still reports how many ticks were consumed up to (but not including)
    # the failing tick. The ``finally`` block reads this counter when writing
    # the failure metrics blob.
    ticks_seen = 0

    try:
        async for tick in source.iter_ticks(time_range):
            book.update(tick)
            tick_timestamp = tick.timestamp
            signal = strategy.on_tick(tick, params, tick_timestamp)

            tick_pnl = Decimal("0")
            if signal is not None:
                # Default arg binds tick.timestamp at definition time
                # (late-binding guard) so each closure captures its own tick.
                def _tick_clock(ts: datetime = tick_timestamp) -> datetime:
                    return ts

                result = match_order(signal, tick, now_fn=_tick_clock)
                realised = settlement(signal, result)
                fill_log.append((result, realised))
                tick_pnl = realised

            running_pnl += tick_pnl
            per_tick_pnl.append(tick_pnl)
            equity_curve.append(running_pnl)
            ticks_seen += 1
    except BaseException as exc:
        # Seal the run row with a sentinel failure blob so ``ended_at`` is
        # populated even when the replay raised. We only persist when the
        # caller opted into DB mode (both ``db`` and ``run_id`` present);
        # the exception is re-raised so the caller observes the failure.
        if db is not None and run_id is not None:
            failure_metrics: dict[str, Any] = {
                "status": "failed",
                "error": repr(exc),
                "n_ticks_consumed": ticks_seen,
            }
            await crud.end_run(db, run_id, metrics=failure_metrics)
        raise

    ended_at = clock()

    realised_pnls = [pnl for _result, pnl in fill_log]
    result_dict: BacktestResult = {
        "sharpe": sharpe(per_tick_pnl),
        "total_pnl_gbp": total_pnl_gbp_from_pnls(realised_pnls),
        "max_drawdown_gbp": max_drawdown_gbp(equity_curve),
        "n_trades": sum(1 for result, _pnl in fill_log if result.filled_stake > Decimal("0")),
        "win_rate": win_rate_from_pnls(realised_pnls),
        "n_ticks_consumed": ticks_seen,
        "started_at": started_at,
        "ended_at": ended_at,
    }

    if db is not None and run_id is not None:
        await crud.end_run(db, run_id, metrics=_jsonable(result_dict))

    return result_dict


def _jsonable(result: BacktestResult) -> dict[str, Any]:
    """Coerce the BacktestResult into a jsonb-safe dict for persistence.

    Single JSONB boundary: ``crud.end_run`` calls ``json.dumps(metrics)``
    and neither ``Decimal`` nor ``datetime`` is natively serialisable, so
    we stringify them here. Centralising the coercion in the harness keeps
    ``crud.end_run`` free of per-service coercion logic — every caller
    that wants to persist a ``BacktestResult`` goes through this helper.
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

"""Workflow functions for the research orchestrator.

These functions implement the core research loop:

- ``hypothesize`` — full agentic hypothesis generation cycle (Phase 6c):
  context → ideate → codegen → validate → sandbox → backtest → persist → wiki.
- ``run_backtest`` — production path: a thin delegate onto
  ``backtest_engine.run_backtest`` so the orchestrator can keep calling
  ``workflow.run_backtest`` in its own namespace.
- ``promote`` — advance a strategy through the lifecycle via the registry
  gate.

Trust boundary — exec() usage
------------------------------
``hypothesize()`` executes LLM-generated source code via ``exec()`` when
constructing the ``StrategyModule`` adapter for the harness.  This is safe
because:

1. The source string first passes the strict AST whitelist validator
   (``ast_validator.validate``), which rejects all dangerous node types
   (Import of non-whitelisted modules, ``eval``, ``exec``, ``open``,
   ``__import__``, class definitions, decorators, ``try``/``except``, etc.)
   before any code is run.

2. The source string additionally passes through the subprocess sandbox
   (``sandbox_runner.run_in_sandbox``) which runs the code in a spawned
   child with network blocked and builtins stripped.

Only after both safety checks pass is ``exec()`` called in the parent
process, within a restricted namespace ``{"__builtins__": {}}``.  The
parent-side ``exec`` is therefore belt-and-braces over already-validated
code, never the primary defence.
"""

from __future__ import annotations

import builtins
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from algobet_common.bus import BusClient, Topic
from algobet_common.db import Database
from algobet_common.schemas import MarketData, OrderSignal, Venue
from backtest_engine.harness import BacktestResult
from backtest_engine.harness import run_backtest as _harness_run_backtest
from backtest_engine.strategy_protocol import StrategyModule, TickSource
from strategy_registry import crud
from strategy_registry.models import Status, Strategy

from .ast_validator import validate as _ast_validate
from .config import OrchestratorSettings
from .context_builder import ContextBuilder
from .errors import OrchestratorError
from .llm_client import BudgetExceeded, LLMClient
from .sandbox_runner import run_in_sandbox
from .schemas import ResearchEvent
from .spend_tracker import SpendTracker
from .types import CycleReport, SpecOutcome, StrategySpec

logger = logging.getLogger(__name__)

# Transitions the orchestrator is explicitly forbidden from requesting.
# paper → awaiting-approval is a human decision via the dashboard.
# awaiting-approval → live requires dashboard approval with approved_by.
_FORBIDDEN_TRANSITIONS: frozenset[Status] = frozenset({Status.LIVE, Status.AWAITING_APPROVAL})


# ---------------------------------------------------------------------------
# Internal: StrategyModule adapter wrapping exec'd compute_signal
# ---------------------------------------------------------------------------


class _GeneratedStrategy:
    """Adapts an exec'd ``compute_signal(snapshot, params)`` into StrategyModule.

    This adapter wraps the ``compute_signal`` function obtained by exec'ing
    the validated, sandbox-checked LLM source so that the backtest harness
    can call it via the ``StrategyModule.on_tick`` protocol.

    The ``on_tick`` method receives a ``MarketData`` snapshot from the harness.
    It converts it to a dict so ``compute_signal`` can use ``.get()`` as the
    LLM-generated code expects.  The returned ``float | None`` signal is
    converted to an ``OrderSignal | None`` using the spec's default stake.

    Note: ``exec()`` is called *after* AST validation and sandbox checks —
    see the module-level trust boundary docstring.
    """

    def __init__(self, compute_signal_fn: Any, spec: StrategySpec) -> None:
        self._fn = compute_signal_fn
        self._spec = spec

    @staticmethod
    def _snapshot_to_dict(snapshot: MarketData) -> dict[str, Any]:
        """Convert a MarketData pydantic model to a plain dict for compute_signal."""
        best_bid = float(snapshot.bids[0][0]) if snapshot.bids else 0.0
        best_ask = float(snapshot.asks[0][0]) if snapshot.asks else 0.0
        best_bid_depth = float(snapshot.bids[0][1]) if snapshot.bids else 0.0
        best_ask_depth = float(snapshot.asks[0][1]) if snapshot.asks else 0.0
        mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0
        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "best_bid_depth": best_bid_depth,
            "best_ask_depth": best_ask_depth,
            "mid": mid,
            "market_id": snapshot.market_id,
            "venue": str(snapshot.venue),
        }

    def on_tick(
        self,
        snapshot: MarketData,
        params: dict[str, Any],
        now: datetime,
    ) -> OrderSignal | None:
        """Delegate to the generated compute_signal function."""
        snap_dict = self._snapshot_to_dict(snapshot)
        try:
            signal_value = self._fn(snap_dict, params)
        except Exception:
            return None

        if signal_value is None:
            return None

        # Convert float signal to OrderSignal.
        # Positive signal → BACK; negative signal → LAY.
        from algobet_common.schemas import OrderSide

        side = OrderSide.BACK if float(signal_value) >= 0 else OrderSide.LAY
        # Use a minimal default price/stake.  The backtest fills model handles
        # the actual execution; these are plausible defaults.
        default_price = Decimal("2.0")  # evens — generic placeholder
        default_stake = Decimal("10.0")

        return OrderSignal(
            strategy_id=self._spec.name,
            mode="paper",
            venue=Venue(snapshot.venue),
            market_id=snapshot.market_id,
            side=side,
            stake=default_stake,
            price=default_price,
            selection_id=None,
        )


def _build_strategy_module(source: str, spec: StrategySpec) -> StrategyModule:
    """Exec validated source and return a StrategyModule adapter.

    Called ONLY after ``ast_validator.validate`` has returned ``ok=True``
    and ``sandbox_runner.run_in_sandbox`` has returned ``status=="ok"``.
    The exec namespace uses a restricted ``__builtins__`` dict that allows
    only the AST-whitelisted stdlib modules (``math``, ``statistics``,
    ``dataclasses``) to be imported.  All other builtins that have been
    cleared are belt-and-braces on top of the AST validation that already
    rejected dangerous nodes.
    """
    import dataclasses
    import math
    import statistics

    _ALLOWED = frozenset({"math", "statistics", "dataclasses"})
    _ALLOWED_MODULES = {"math": math, "statistics": statistics, "dataclasses": dataclasses}
    _real_import = builtins.__import__

    def _restricted_import(
        name: str, glb: Any = None, loc: Any = None, fromlist: Any = (), level: int = 0
    ) -> Any:
        top = name.split(".")[0]
        if top not in _ALLOWED:
            raise ImportError(
                f"generated strategy may only import whitelisted modules; got '{name}'"
            )
        return _real_import(name, glb, loc, fromlist, level)

    restricted_builtins: dict[str, Any] = {"__import__": _restricted_import}
    exec_ns: dict[str, Any] = {
        "__builtins__": restricted_builtins,
        **_ALLOWED_MODULES,
    }
    exec(compile(source, "<generated>", "exec"), exec_ns)

    compute_signal = exec_ns.get("compute_signal")
    if compute_signal is None:
        raise OrchestratorError(
            f"Generated source for '{spec.name}' does not define compute_signal"
        )
    return _GeneratedStrategy(compute_signal, spec)


# ---------------------------------------------------------------------------
# Internal: extract spend delta from tracker
# ---------------------------------------------------------------------------


def _spend_delta(tracker: SpendTracker, before: float) -> float:
    """Return how much was spent since ``before`` was sampled."""
    return max(0.0, tracker.cumulative_today_usd() - before)


# ---------------------------------------------------------------------------
# Internal: build a minimal sample snapshot for sandbox import check
# ---------------------------------------------------------------------------


def _make_sample_snapshot() -> dict[str, Any]:
    """Return a minimal snapshot dict for the sandbox import check."""
    return {
        "best_bid": 1.9,
        "best_ask": 2.1,
        "best_bid_depth": 100.0,
        "best_ask_depth": 80.0,
        "mid": 2.0,
        "mid_history": [2.0] * 25,
        "microprice_history": [2.0] * 15,
        "spread_history": [0.1] * 55,
        "market_id": "1.sample",
        "venue": "betfair",
    }


# ---------------------------------------------------------------------------
# hypothesize()
# ---------------------------------------------------------------------------


async def hypothesize(
    cycle_id: str,
    *,
    db: Database | None = None,
    bus: BusClient | None = None,
    llm_client: LLMClient,
    spend_tracker: SpendTracker,
    context_builder: ContextBuilder,
    settings: OrchestratorSettings,
    # Test-injection hooks (optional; real code can leave as None → defaults)
    backtest_runner: Callable[..., Awaitable[BacktestResult]] | None = None,
    wiki_writer: Callable[..., Path] | None = None,
    tick_source_factory: Callable[[str], TickSource] | None = None,
    time_range: tuple[datetime, datetime] | None = None,
) -> CycleReport:
    """Full agentic hypothesis generation cycle.

    Orchestrates: context → ideate → (per spec) codegen → validate → sandbox
    → backtest → persist → wiki.

    On per-spec failures the cycle continues with the remaining specs; only
    ``BudgetExceeded`` aborts the entire cycle.

    Parameters
    ----------
    cycle_id:
        Caller-supplied identifier for this generation cycle.
    db:
        Optional Postgres database handle.  When ``None``, registry inserts
        and research-event publishes are skipped; the cycle still runs all
        in-process stages and returns a complete ``CycleReport``.
    bus:
        Optional Redis bus client.  When ``None``, research-event publishes
        are skipped.
    llm_client:
        Configured ``LLMClient`` (mock or live).
    spend_tracker:
        ``SpendTracker`` used for budget accounting.
    context_builder:
        ``ContextBuilder`` producing the 4-layer ideation context.
    settings:
        ``OrchestratorSettings`` controlling batch size, sandbox limits, etc.
    backtest_runner:
        Injected callable with the same signature as ``run_backtest``; used
        by tests to avoid live DB + harness overhead.  Defaults to the
        production ``run_backtest`` when ``None``.
    wiki_writer:
        Injected callable ``(spec, source, result) -> Path``; used by tests.
        When ``None``, wiki writes are skipped.
    tick_source_factory:
        Injected ``(market_id: str) -> TickSource``; used by tests to supply
        deterministic synthetic ticks.  When ``None``, a dummy in-memory
        source is constructed (produces zero ticks, useful for offline tests
        that only want validation/sandbox stages).
    time_range:
        Backtest time range.  Defaults to the last 24 hours when ``None``.

    Returns
    -------
    CycleReport
        Complete summary of the cycle, including per-spec outcomes and spend.
    """
    logger.info("hypothesize: starting cycle %s", cycle_id)

    # ------------------------------------------------------------------
    # Resolve defaults
    # ------------------------------------------------------------------
    effective_runner: Callable[..., Awaitable[BacktestResult]] = (
        backtest_runner if backtest_runner is not None else _harness_run_backtest
    )
    if time_range is None:
        now_utc = datetime.now(UTC)
        from datetime import timedelta

        time_range = (now_utc - timedelta(hours=24), now_utc)

    # ------------------------------------------------------------------
    # Stage 1: build ideation context
    # ------------------------------------------------------------------
    context = await context_builder.build(cycle_id)

    # ------------------------------------------------------------------
    # Stage 2: ideation (budget guard inside llm_client)
    # ------------------------------------------------------------------
    spend_before_ideation = spend_tracker.cumulative_today_usd()
    try:
        specs: list[StrategySpec] = llm_client.ideate(context)
    except BudgetExceeded as exc:
        logger.warning("hypothesize: BudgetExceeded during ideation — aborting cycle %s", cycle_id)
        return CycleReport(
            cycle_id=cycle_id,
            outcomes=(),
            ideation_spend_usd=0.0,
            codegen_spend_usd=0.0,
            total_spend_usd=0.0,
            aborted=True,
            abort_reason=f"budget exceeded during ideation: {exc}",
        )

    ideation_spend = _spend_delta(spend_tracker, spend_before_ideation)
    logger.info(
        "hypothesize: ideation produced %d specs (spend=%.4f USD)", len(specs), ideation_spend
    )

    # ------------------------------------------------------------------
    # Stage 3-8: per-spec pipeline
    # ------------------------------------------------------------------
    outcomes: list[SpecOutcome] = []
    codegen_spend_total: float = 0.0

    for spec in specs:
        outcome = await _process_spec(
            spec=spec,
            cycle_id=cycle_id,
            db=db,
            bus=bus,
            llm_client=llm_client,
            spend_tracker=spend_tracker,
            settings=settings,
            effective_runner=effective_runner,
            wiki_writer=wiki_writer,
            tick_source_factory=tick_source_factory,
            time_range=time_range,
        )
        if outcome is None:
            # BudgetExceeded mid-loop — abort with outcomes so far
            logger.warning(
                "hypothesize: BudgetExceeded during codegen for spec '%s' — aborting", spec.name
            )
            return CycleReport(
                cycle_id=cycle_id,
                outcomes=tuple(outcomes),
                ideation_spend_usd=ideation_spend,
                codegen_spend_usd=codegen_spend_total,
                total_spend_usd=ideation_spend + codegen_spend_total,
                aborted=True,
                abort_reason=f"budget exceeded during codegen for spec '{spec.name}'",
            )

        spec_codegen_spend, spec_outcome = outcome
        codegen_spend_total += spec_codegen_spend
        outcomes.append(spec_outcome)

    # ------------------------------------------------------------------
    # Return final report
    # ------------------------------------------------------------------
    total = ideation_spend + codegen_spend_total
    report = CycleReport(
        cycle_id=cycle_id,
        outcomes=tuple(outcomes),
        ideation_spend_usd=ideation_spend,
        codegen_spend_usd=codegen_spend_total,
        total_spend_usd=total,
        aborted=False,
        abort_reason=None,
    )
    logger.info(
        "hypothesize: cycle %s complete — %d outcomes, total_spend=%.4f USD",
        cycle_id,
        len(outcomes),
        total,
    )
    return report


# ---------------------------------------------------------------------------
# Internal: per-spec pipeline
# ---------------------------------------------------------------------------


async def _process_spec(
    *,
    spec: StrategySpec,
    cycle_id: str,
    db: Database | None,
    bus: BusClient | None,
    llm_client: LLMClient,
    spend_tracker: SpendTracker,
    settings: OrchestratorSettings,
    effective_runner: Callable[..., Awaitable[BacktestResult]],
    wiki_writer: Callable[..., Path] | None,
    tick_source_factory: Callable[[str], TickSource] | None,
    time_range: tuple[datetime, datetime],
) -> tuple[float, SpecOutcome] | None:
    """Process a single spec through all pipeline stages.

    Returns ``None`` when ``BudgetExceeded`` is raised (signals the caller to
    abort the cycle).  Otherwise returns ``(codegen_spend_usd, SpecOutcome)``.
    """
    spend_before_codegen = spend_tracker.cumulative_today_usd()

    # ------------------------------------------------------------------
    # Step 3a: codegen
    # ------------------------------------------------------------------
    try:
        source: str = llm_client.codegen(spec)
    except BudgetExceeded:
        return None  # signal abort

    codegen_spend = _spend_delta(spend_tracker, spend_before_codegen)

    # ------------------------------------------------------------------
    # Step 3b: AST validation
    # ------------------------------------------------------------------
    vr = _ast_validate(source)
    if not vr.ok:
        first_violation = vr.violations[0] if vr.violations else None
        reason = first_violation.reason if first_violation else "unknown validation failure"
        logger.info("hypothesize: spec '%s' failed AST validation: %s", spec.name, reason)
        return codegen_spend, SpecOutcome(
            spec_name=spec.name,
            stage="validation",
            status="failed",
            reason=reason,
            strategy_id=None,
            wiki_path=None,
            backtest_summary=None,
        )

    # ------------------------------------------------------------------
    # Step 3c: sandbox import check
    # ------------------------------------------------------------------
    sample_snapshot = _make_sample_snapshot()
    sample_params = {k: v.default for k, v in spec.params.items()}
    sandbox_result = run_in_sandbox(
        module_source=source,
        entry_callable="compute_signal",
        args=(sample_snapshot, sample_params),
        cpu_seconds=settings.hypothesis_sandbox_cpu_seconds,
        mem_mb=settings.hypothesis_sandbox_mem_mb,
        wall_timeout_s=settings.hypothesis_sandbox_wall_timeout_s,
    )

    if sandbox_result.status != "ok":
        reason = sandbox_result.reason or sandbox_result.error_repr or "sandbox check failed"
        logger.info(
            "hypothesize: spec '%s' failed sandbox check (status=%s): %s",
            spec.name,
            sandbox_result.status,
            reason,
        )
        # Map timeout to a descriptive stage label in the reason field
        sandbox_stage_reason = reason
        if sandbox_result.status == "timeout":
            sandbox_stage_reason = f"sandbox-kill: {reason}"
        return codegen_spend, SpecOutcome(
            spec_name=spec.name,
            stage="sandbox",
            status="failed",
            reason=sandbox_stage_reason,
            strategy_id=None,
            wiki_path=None,
            backtest_summary=None,
        )

    # ------------------------------------------------------------------
    # Step 4: build StrategyModule adapter (post-validation exec)
    # ------------------------------------------------------------------
    try:
        strategy_module = _build_strategy_module(source, spec)
    except OrchestratorError as exc:
        return codegen_spend, SpecOutcome(
            spec_name=spec.name,
            stage="validation",
            status="failed",
            reason=str(exc),
            strategy_id=None,
            wiki_path=None,
            backtest_summary=None,
        )

    # ------------------------------------------------------------------
    # Step 5: backtest
    # ------------------------------------------------------------------
    params_defaults = {k: v.default for k, v in spec.params.items()}

    # Resolve tick source
    if tick_source_factory is not None:
        tick_source = tick_source_factory(spec.name)
    else:
        # Offline fallback: empty async iterator — produces zero ticks.
        tick_source = _EmptyTickSource()

    try:
        backtest_result = await effective_runner(
            strategy=strategy_module,
            params=params_defaults,
            source=tick_source,
            time_range=time_range,
            db=db,
            strategy_id=None,
        )
    except Exception as exc:
        return codegen_spend, SpecOutcome(
            spec_name=spec.name,
            stage="backtest",
            status="failed",
            reason=f"backtest raised: {exc!r}",
            strategy_id=None,
            wiki_path=None,
            backtest_summary=None,
        )

    # Zero-trades guard
    trade_count = backtest_result.get("n_trades", 0)
    if trade_count == 0:
        logger.info("hypothesize: spec '%s' produced zero trades — skipping", spec.name)
        return codegen_spend, SpecOutcome(
            spec_name=spec.name,
            stage="backtest",
            status="failed",
            reason="backtest returned zero trades",
            strategy_id=None,
            wiki_path=None,
            backtest_summary=None,
        )

    # ------------------------------------------------------------------
    # Step 6: persist to registry (skip when db is None)
    # ------------------------------------------------------------------
    strategy_id_str: str | None = None
    if db is not None:
        strategy = await crud.create_strategy(
            db,
            slug=spec.name,
            parameters=params_defaults,
            wiki_path=None,  # will be updated after wiki write
        )
        strategy_id_str = str(strategy.id)
        logger.info("hypothesize: persisted spec '%s' → strategy_id=%s", spec.name, strategy_id_str)

    # ------------------------------------------------------------------
    # Step 7: write wiki (skip when wiki_writer is None)
    # ------------------------------------------------------------------
    wiki_path_str: str | None = None
    if wiki_writer is not None:
        try:
            wiki_path = wiki_writer(spec, source, backtest_result)
            wiki_path_str = str(wiki_path)
        except Exception as exc:
            logger.warning("hypothesize: wiki write failed for spec '%s': %s", spec.name, exc)

    # ------------------------------------------------------------------
    # Step 8: publish research event (skip when bus is None)
    # ------------------------------------------------------------------
    if bus is not None and strategy_id_str is not None:
        event = ResearchEvent(
            event_type="hypothesis_generated",
            strategy_id=strategy_id_str,
            from_status="",
            to_status=str(Status.HYPOTHESIS),
            timestamp=datetime.now(UTC),
        )
        try:
            await bus.publish(Topic.RESEARCH_EVENTS, event)
        except Exception as exc:
            logger.warning(
                "hypothesize: failed to publish research event for '%s': %s", spec.name, exc
            )

    # ------------------------------------------------------------------
    # Build backtest summary (JSON-safe subset of BacktestResult)
    # ------------------------------------------------------------------
    backtest_summary: dict[str, Any] = {
        "n_trades": int(backtest_result.get("n_trades", 0)),
        "sharpe": float(backtest_result.get("sharpe", 0.0)),
        "win_rate": float(backtest_result.get("win_rate", 0.0)),
        "total_pnl_gbp": str(backtest_result.get("total_pnl_gbp", "0")),
        "n_ticks_consumed": int(backtest_result.get("n_ticks_consumed", 0)),
    }

    return codegen_spend, SpecOutcome(
        spec_name=spec.name,
        stage="persisted",
        status="passed",
        reason=None,
        strategy_id=strategy_id_str,
        wiki_path=wiki_path_str,
        backtest_summary=backtest_summary,
    )


# ---------------------------------------------------------------------------
# Internal: empty tick source (offline fallback)
# ---------------------------------------------------------------------------


class _EmptyTickSource:
    """A TickSource that yields zero ticks (offline fallback for tests)."""

    async def iter_ticks(
        self,
        time_range: tuple[datetime, datetime],
    ) -> AsyncIterator[MarketData]:
        return
        yield  # pragma: no cover -- yield makes this an async generator


# ---------------------------------------------------------------------------
# run_backtest (kept unchanged — existing tests depend on this)
# ---------------------------------------------------------------------------


async def run_backtest(
    strategy_id: uuid.UUID,
    strategy: StrategyModule,
    params: dict[str, Any],
    source: TickSource,
    time_range: tuple[datetime, datetime],
    db: Database,
) -> BacktestResult:
    """Production backtest path — thin delegate onto the real harness.

    The orchestrator keeps its own ``workflow.run_backtest`` name so callers
    (``runner.run_once``) don't need to import ``backtest_engine`` directly.
    All DB bookkeeping (``strategy_runs`` start_run / end_run) is handled
    inside the harness when ``db`` + ``strategy_id`` are supplied.
    """
    logger.info(
        "run_backtest: dispatching harness for strategy %s over [%s, %s]",
        strategy_id,
        time_range[0].isoformat(),
        time_range[1].isoformat(),
    )
    return await _harness_run_backtest(
        strategy=strategy,
        params=params,
        source=source,
        time_range=time_range,
        db=db,
        strategy_id=strategy_id,
    )


# ---------------------------------------------------------------------------
# promote (kept unchanged — existing tests depend on this)
# ---------------------------------------------------------------------------


async def promote(
    db: Database,
    bus: BusClient,
    strategy_id: uuid.UUID,
    to_status: Status,
) -> Strategy:
    """Advance a strategy to a new lifecycle status.

    Enforces the orchestrator's authority boundary: transitions to
    LIVE or AWAITING_APPROVAL are reserved for humans via the dashboard
    and will raise OrchestratorError before any DB call.

    Publishes a ResearchEvent to Topic.RESEARCH_EVENTS only after the
    transition succeeds, so consumers never see misleading events.
    """
    if to_status in _FORBIDDEN_TRANSITIONS:
        raise OrchestratorError(
            f"orchestrator may not request transition to {to_status}; "
            "use the dashboard approval route"
        )

    current = await crud.get_strategy(db, strategy_id)
    from_status = current.status

    updated = await crud.transition(db, strategy_id, to_status)

    event = ResearchEvent(
        event_type="strategy_transition",
        strategy_id=str(strategy_id),
        from_status=str(from_status),
        to_status=str(to_status),
        timestamp=datetime.now(UTC),
    )
    await bus.publish(Topic.RESEARCH_EVENTS, event)

    logger.info(
        "promote: strategy %s transitioned %s → %s",
        strategy_id,
        from_status,
        to_status,
    )
    return updated

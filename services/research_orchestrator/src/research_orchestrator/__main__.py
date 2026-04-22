"""CLI entrypoint for the research orchestrator.

Usage:
    SERVICE_NAME=research-orchestrator uv run python -m research_orchestrator run
    uv run orchestrator hypothesize [--dry-run] [--no-backtest]
    uv run orchestrator spend-today
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from algobet_common.bus import BusClient
from algobet_common.config import Settings
from algobet_common.db import Database
from backtest_engine.harness import BacktestResult
from backtest_engine.strategy_protocol import TickSource

from .config import OrchestratorSettings
from .context_builder import ContextBuilder
from .llm_client import LLMClient
from .runner import run_once
from .spend_tracker import SpendTracker
from .types import CycleReport, SpecOutcome, StrategySpec
from .workflow import hypothesize as _hypothesize

logging.basicConfig(level=logging.INFO)

app = typer.Typer(help="Research Orchestrator - single-iteration research loop.")

# ---------------------------------------------------------------------------
# Module-level constant for the spend DB path (patched by tests)
# ---------------------------------------------------------------------------

_default_spend_db_path: Path = (
    Path(__file__).parents[5] / "var" / "research_orchestrator" / "spend.db"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_cycle_report(report: CycleReport) -> None:
    """Print a human-readable summary of a CycleReport to stdout."""
    typer.echo(f"Cycle: {report.cycle_id}")
    typer.echo(f"Aborted: {report.aborted}")
    if report.abort_reason:
        typer.echo(f"Abort reason: {report.abort_reason}")
    typer.echo(f"Ideation spend: ${report.ideation_spend_usd:.4f}")
    typer.echo(f"Codegen spend:  ${report.codegen_spend_usd:.4f}")
    typer.echo(f"Total spend:    ${report.total_spend_usd:.4f}")
    typer.echo(f"Outcomes ({len(report.outcomes)}):")
    for outcome in report.outcomes:
        _print_spec_outcome(outcome)


def _print_spec_outcome(outcome: SpecOutcome) -> None:
    """Print one SpecOutcome line."""
    status_str = f"[{outcome.status.upper()}]"
    stage_str = outcome.stage
    reason_str = f" - {outcome.reason}" if outcome.reason else ""
    typer.echo(f"  {status_str} {outcome.spec_name} @ {stage_str}{reason_str}")
    if outcome.backtest_summary:
        bs = outcome.backtest_summary
        sharpe = float(bs.get("sharpe") or 0.0)
        win_rate = float(bs.get("win_rate") or 0.0)
        typer.echo(
            f"    backtest: n_trades={bs.get('n_trades')} "
            f"sharpe={sharpe:.3f} "
            f"win_rate={win_rate:.3f} "
            f"pnl={bs.get('total_pnl_gbp')}"
        )


def _make_fake_runner() -> Callable[..., Awaitable[BacktestResult]]:
    """Return a fake backtest runner that produces a single-trade result."""

    async def _fake(
        *,
        strategy: Any,
        params: dict[str, Any],
        source: TickSource,
        time_range: tuple[datetime, datetime],
        db: Any,
        strategy_id: Any,
    ) -> BacktestResult:
        now = datetime.now(UTC)
        return BacktestResult(
            sharpe=0.0,
            total_pnl_gbp=Decimal("0"),
            max_drawdown_gbp=Decimal("0"),
            n_trades=1,
            win_rate=0.0,
            n_ticks_consumed=0,
            started_at=now - timedelta(hours=1),
            ended_at=now,
        )

    return _fake


# ---------------------------------------------------------------------------
# Command: run (pre-existing - do not modify behaviour)
# ---------------------------------------------------------------------------


@app.command()  # type: ignore[misc]
def run() -> None:
    """Run one iteration of the research loop (hypothesis -> backtest -> paper)."""
    settings = Settings(service_name="research-orchestrator")
    db = Database(settings.postgres_dsn)
    bus = BusClient(settings.redis_url, service_name=settings.service_name)

    async def _main() -> None:
        await db.connect()
        await bus.connect()
        try:
            await run_once(db, bus, settings)
        finally:
            await db.close()
            await bus.close()

    asyncio.run(_main())


# ---------------------------------------------------------------------------
# Command: hypothesize
# ---------------------------------------------------------------------------


@app.command()  # type: ignore[misc]
def hypothesize(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Execute stages 1-5 (context, ideate, codegen, validate, sandbox) only. "
            "Skips backtest, registry, and wiki writes. "
            "Prints generated specs and code to stdout."
        ),
    ),
    no_backtest: bool = typer.Option(
        False,
        "--no-backtest",
        help="Run full cycle but skip the backtest stage. Useful for debugging.",
    ),
) -> None:
    """Generate hypotheses: context -> ideate -> codegen -> validate -> sandbox -> backtest."""
    settings = OrchestratorSettings()

    # Spend tracker - use module-level path (tests can patch it)
    spend_db_path = _default_spend_db_path
    spend_db_path.parent.mkdir(parents=True, exist_ok=True)
    spend_tracker = SpendTracker(db_path=spend_db_path)

    llm_client = LLMClient(settings=settings, spend_tracker=spend_tracker)
    context_builder = ContextBuilder(registry_repo=None, timescale_query=None)

    cycle_id = str(uuid.uuid4())

    # Collect (spec, source) pairs when dry_run is active so we can print them.
    collected_sources: list[tuple[StrategySpec, str]] = []

    def _sink(spec: StrategySpec, source: str) -> None:
        collected_sources.append((spec, source))

    sink = _sink if dry_run else None
    fake_runner = _make_fake_runner() if (dry_run or no_backtest) else None

    if dry_run:
        typer.echo("[dry-run] Skipping backtest, registry, and wiki writes.")
    elif no_backtest:
        typer.echo("[no-backtest] Skipping backtest stage.")

    async def _run() -> CycleReport:
        return await _hypothesize(
            cycle_id,
            db=None,
            bus=None,
            llm_client=llm_client,
            spend_tracker=spend_tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=fake_runner,
            wiki_writer=None,
            spec_source_sink=sink,
        )

    report = asyncio.run(_run())
    _print_cycle_report(report)

    # Print generated code after the cycle report (dry-run only)
    if dry_run and collected_sources:
        typer.echo("")
        typer.echo("=" * 60)
        typer.echo("Generated strategy source code:")
        typer.echo("=" * 60)
        for spec, source in collected_sources:
            typer.echo(f"\n--- {spec.name} ---")
            typer.echo(source)


# ---------------------------------------------------------------------------
# Command: spend-today
# ---------------------------------------------------------------------------


@app.command(name="spend-today")  # type: ignore[misc]
def spend_today() -> None:
    """Print today's cumulative xAI API spend and the daily cap."""
    settings = OrchestratorSettings()

    spend_db_path = _default_spend_db_path
    spend_db_path.parent.mkdir(parents=True, exist_ok=True)
    spend_tracker = SpendTracker(db_path=spend_db_path)

    cumulative = spend_tracker.cumulative_today_usd()
    cap = settings.hypothesis_daily_usd_cap
    typer.echo(f"Spend today: ${cumulative:.2f} / ${cap:.2f} cap")


if __name__ == "__main__":
    app()

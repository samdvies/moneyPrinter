"""Tests for the rewritten hypothesize() function (Phase 6c Task 6).

All tests are offline — no Postgres, no Redis, no live xAI calls.

Sandbox isolation note
----------------------
The real ``run_in_sandbox`` spawns a subprocess, which can behave differently
inside pytest (Windows multiprocessing, environment setup) vs a plain Python
script.  Since ``sandbox_runner`` has its own exhaustive test suite
(``test_sandbox_runner.py``), these workflow tests mock out ``run_in_sandbox``
to return a controlled ``SandboxResult``.  This isolates the workflow logic
from subprocess lifecycle concerns and keeps the test suite fast.

The exception is test_3 (sandbox-timeout) which explicitly simulates a
``status="timeout"`` result to verify the workflow records it correctly.

Five plan-required scenarios:
1. Happy path — all 4 specs pass validation + sandbox → 4 persisted outcomes.
2. 2 specs fail AST validation → 2 outcomes at "validation" stage.
3. 1 spec sandbox-timeouts → recorded as sandbox-kill.
4. BudgetExceeded during ideation → cycle aborts, no partial writes.
5. Backtest returns zero trades → strategy not persisted.

Additional:
6. BudgetExceeded mid-codegen (spec 2 of 4) → spec-1 success preserved,
   abort_reason names spec 2.
7. CycleReport.total_spend_usd == ideation_spend_usd + codegen_spend_usd.
8. db=None and bus=None — cycle still completes with a CycleReport.

Phase 6c Task 8 additions:
9. wiki_root wiring — 4 proposed-strategy files + daily log written.
10. Two cycles same day → daily log has 2 Hypothesis Cycle sections.
11. Round-trip via strategy_registry.wiki_loader — no parse errors.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from algobet_common.schemas import MarketData, Venue
from research_orchestrator.config import OrchestratorSettings
from research_orchestrator.context_builder import ContextBuilder
from research_orchestrator.llm_client import BudgetExceeded, LLMClient
from research_orchestrator.sandbox_runner import SandboxResult
from research_orchestrator.spend_tracker import SpendTracker
from research_orchestrator.types import CycleReport, StrategySpec
from research_orchestrator.workflow import hypothesize

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CASSETTE_DIR = Path(__file__).parent / "fixtures" / "llm_cassettes"
_SPEC_NAMES = [
    "bollinger_reversion",
    "microprice_drift",
    "spread_capture",
    "book_imbalance_fade",
]

_START = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
_END = _START + timedelta(hours=2)
_TIME_RANGE = (_START, _END)

# Canonical "ok" SandboxResult — no process spawned; used as the default mock.
_SANDBOX_OK = SandboxResult(status="ok", value=None, error_repr=None, reason=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path) -> OrchestratorSettings:
    return OrchestratorSettings(
        xai_api_key="mock",
        xai_cassette_dir=_CASSETTE_DIR,
        hypothesis_sandbox_cpu_seconds=5,
        hypothesis_sandbox_mem_mb=256,
        hypothesis_sandbox_wall_timeout_s=15.0,
    )


def _make_spend_tracker(tmp_path: Path) -> SpendTracker:
    return SpendTracker(db_path=tmp_path / "spend.db")


def _make_llm_client(settings: OrchestratorSettings, tracker: SpendTracker) -> LLMClient:
    return LLMClient(settings=settings, spend_tracker=tracker)


def _make_context_builder() -> ContextBuilder:
    return ContextBuilder(registry_repo=None, timescale_query=None)


def _make_backtest_result(n_trades: int = 5) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "sharpe": 1.2,
        "total_pnl_gbp": Decimal("15.00"),
        "max_drawdown_gbp": Decimal("3.00"),
        "n_trades": n_trades,
        "win_rate": 0.6,
        "n_ticks_consumed": 100,
        "started_at": now - timedelta(hours=1),
        "ended_at": now,
    }


async def _fake_backtest_runner(**kwargs: Any) -> Any:
    return _make_backtest_result(n_trades=5)


async def _zero_trade_backtest_runner(**kwargs: Any) -> Any:
    return _make_backtest_result(n_trades=0)


def _fake_wiki_writer(tmp_path: Path) -> Any:
    written: list[tuple[StrategySpec, str, dict[str, Any]]] = []

    def writer(spec: StrategySpec, source: str, result: dict[str, Any]) -> Path:
        p = tmp_path / "wiki" / f"{spec.name}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {spec.name}\n", encoding="utf-8")
        written.append((spec, source, result))
        return p

    writer.calls = written  # type: ignore[attr-defined]
    return writer


class _DummyTickSource:
    async def iter_ticks(self, time_range: tuple[datetime, datetime]) -> AsyncIterator[MarketData]:
        start, end = time_range
        step = (end - start) / 10
        for i in range(10):
            ts = start + step * i
            yield MarketData(
                venue=Venue.BETFAIR,
                market_id="1.test",
                timestamp=ts,
                bids=[(Decimal("1.9"), Decimal("100"))],
                asks=[(Decimal("2.1"), Decimal("80"))],
            )


def _tick_source_factory(market_id: str = "") -> _DummyTickSource:
    return _DummyTickSource()


# ---------------------------------------------------------------------------
# Test 1: Happy path — all 4 specs pass
# ---------------------------------------------------------------------------


async def test_happy_path_all_specs_pass(tmp_path: Path) -> None:
    """All 4 specs pass validation, sandbox (mocked ok), backtest → persisted."""
    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()
    wiki_writer = _fake_wiki_writer(tmp_path)

    with patch("research_orchestrator.workflow.run_in_sandbox", return_value=_SANDBOX_OK):
        report: CycleReport = await hypothesize(
            "cycle-001",
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_writer=wiki_writer,
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    assert not report.aborted, f"cycle aborted unexpectedly: {report.abort_reason}"
    assert report.abort_reason is None
    assert report.cycle_id == "cycle-001"
    assert len(report.outcomes) == 4

    for outcome in report.outcomes:
        assert (
            outcome.status == "passed"
        ), f"spec '{outcome.spec_name}' failed at stage '{outcome.stage}': {outcome.reason}"
        assert outcome.stage == "persisted"
        assert outcome.wiki_path is not None
        assert outcome.backtest_summary is not None
        assert outcome.backtest_summary["n_trades"] == 5

    assert len(wiki_writer.calls) == 4
    assert report.ideation_spend_usd >= 0.0
    assert report.codegen_spend_usd >= 0.0
    spend_sum = report.ideation_spend_usd + report.codegen_spend_usd
    assert abs(report.total_spend_usd - spend_sum) < 1e-9


# ---------------------------------------------------------------------------
# Test 2: 2 specs fail AST validation
# ---------------------------------------------------------------------------


async def test_two_specs_fail_ast_validation(tmp_path: Path) -> None:
    """When 2 of 4 codegen cassettes fail validation, 2 pass and 2 are recorded as failures."""
    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()

    call_count = [0]
    from research_orchestrator.ast_validator import ValidationResult, Violation

    _real_validate = __import__(
        "research_orchestrator.ast_validator", fromlist=["validate"]
    ).validate

    def _patched_validate(source: str) -> ValidationResult:
        call_count[0] += 1
        if call_count[0] <= 2:
            return ValidationResult(
                ok=False,
                module=None,
                violations=(
                    Violation(
                        node_type="Import",
                        line=1,
                        col=0,
                        reason="import of non-whitelisted module 'os'",
                    ),
                ),
            )
        result: ValidationResult = _real_validate(source)
        return result

    with (
        patch("research_orchestrator.workflow._ast_validate", side_effect=_patched_validate),
        patch("research_orchestrator.workflow.run_in_sandbox", return_value=_SANDBOX_OK),
    ):
        report: CycleReport = await hypothesize(
            "cycle-002",
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_writer=_fake_wiki_writer(tmp_path),
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    assert not report.aborted
    assert len(report.outcomes) == 4

    failed = [o for o in report.outcomes if o.status == "failed"]
    passed = [o for o in report.outcomes if o.status == "passed"]
    failed_names = [o.spec_name for o in failed]
    assert len(failed) == 2, f"Expected 2 failures, got {len(failed)}: {failed_names}"
    assert len(passed) == 2

    for o in failed:
        assert o.stage == "validation"
        assert o.reason is not None
        assert "non-whitelisted" in o.reason or "validation" in o.reason.lower()
        assert o.strategy_id is None
        assert o.wiki_path is None


# ---------------------------------------------------------------------------
# Test 3: 1 spec sandbox-timeouts
# ---------------------------------------------------------------------------


async def test_one_spec_sandbox_timeout(tmp_path: Path) -> None:
    """When the sandbox returns timeout for one spec, it is recorded and
    the remaining specs continue processing."""
    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()

    sandbox_timeout = SandboxResult(
        status="timeout",
        value=None,
        error_repr="child exceeded wall-clock timeout of 15.0s",
        reason="wall-clock timeout",
    )
    call_count = [0]

    def _selective_sandbox(*args: Any, **kwargs: Any) -> SandboxResult:
        call_count[0] += 1
        if call_count[0] == 1:
            return sandbox_timeout
        return _SANDBOX_OK

    with patch("research_orchestrator.workflow.run_in_sandbox", side_effect=_selective_sandbox):
        report: CycleReport = await hypothesize(
            "cycle-003",
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_writer=_fake_wiki_writer(tmp_path),
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    assert not report.aborted
    assert len(report.outcomes) == 4

    sandbox_failures = [o for o in report.outcomes if o.stage == "sandbox" and o.status == "failed"]
    assert len(sandbox_failures) == 1
    sb_reason = sandbox_failures[0].reason or ""
    assert "sandbox-kill" in sb_reason or "timeout" in sb_reason.lower()

    persisted = [o for o in report.outcomes if o.stage == "persisted" and o.status == "passed"]
    assert len(persisted) == 3


# ---------------------------------------------------------------------------
# Test 4: BudgetExceeded during ideation → clean abort
# ---------------------------------------------------------------------------


async def test_budget_exceeded_during_ideation(tmp_path: Path) -> None:
    """BudgetExceeded during ideation aborts cleanly with no writes."""
    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()
    wiki_writer = _fake_wiki_writer(tmp_path)

    def _raise_budget(*args: Any, **kwargs: Any) -> None:
        raise BudgetExceeded(estimated_usd=1.0, cap_usd=0.5, cumulative_usd=0.4)

    with (
        patch.object(llm_client, "ideate", side_effect=_raise_budget),
        patch("research_orchestrator.workflow.run_in_sandbox", return_value=_SANDBOX_OK),
    ):
        report: CycleReport = await hypothesize(
            "cycle-004",
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_writer=wiki_writer,
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    assert report.aborted
    assert report.abort_reason is not None
    assert "budget exceeded" in report.abort_reason.lower()
    assert len(report.outcomes) == 0
    assert len(wiki_writer.calls) == 0
    assert report.total_spend_usd == 0.0
    spend_sum = report.ideation_spend_usd + report.codegen_spend_usd
    assert abs(report.total_spend_usd - spend_sum) < 1e-9


# ---------------------------------------------------------------------------
# Test 5: Backtest returns zero trades → strategy not persisted
# ---------------------------------------------------------------------------


async def test_zero_trades_not_persisted(tmp_path: Path) -> None:
    """All backtests returning zero trades produces no persisted outcomes."""
    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()
    wiki_writer = _fake_wiki_writer(tmp_path)

    with patch("research_orchestrator.workflow.run_in_sandbox", return_value=_SANDBOX_OK):
        report: CycleReport = await hypothesize(
            "cycle-005",
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_zero_trade_backtest_runner,
            wiki_writer=wiki_writer,
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    assert not report.aborted

    backtest_failures = [
        o for o in report.outcomes if o.stage == "backtest" and o.status == "failed"
    ]
    assert len(backtest_failures) == 4
    for o in backtest_failures:
        assert o.reason is not None and "zero trades" in o.reason
        assert o.strategy_id is None
        assert o.wiki_path is None

    assert len(wiki_writer.calls) == 0


# ---------------------------------------------------------------------------
# Test 6: BudgetExceeded mid-codegen (spec 2 of 4) — spec-1 preserved
# ---------------------------------------------------------------------------


async def test_budget_exceeded_during_codegen_preserves_spec1(tmp_path: Path) -> None:
    """BudgetExceeded during codegen for spec 2 preserves spec-1 outcome."""
    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()
    wiki_writer = _fake_wiki_writer(tmp_path)

    codegen_call_count = [0]
    _real_codegen = llm_client.codegen

    def _patched_codegen(spec: StrategySpec, cassette_name: Any = None) -> str:
        codegen_call_count[0] += 1
        if codegen_call_count[0] == 2:
            raise BudgetExceeded(estimated_usd=1.0, cap_usd=0.5, cumulative_usd=0.4)
        return _real_codegen(spec, cassette_name)

    with (
        patch.object(llm_client, "codegen", side_effect=_patched_codegen),
        patch("research_orchestrator.workflow.run_in_sandbox", return_value=_SANDBOX_OK),
    ):
        report: CycleReport = await hypothesize(
            "cycle-006",
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_writer=wiki_writer,
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    assert report.aborted
    assert report.abort_reason is not None

    # spec-1 (bollinger_reversion) should be present and passed
    assert len(report.outcomes) == 1
    first = report.outcomes[0]
    assert first.spec_name == _SPEC_NAMES[0]
    assert first.status == "passed"
    assert first.stage == "persisted"


# ---------------------------------------------------------------------------
# Test 7: total_spend_usd == ideation + codegen
# ---------------------------------------------------------------------------


async def test_total_spend_equals_sum(tmp_path: Path) -> None:
    """CycleReport.total_spend_usd must always equal ideation + codegen."""
    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()

    with patch("research_orchestrator.workflow.run_in_sandbox", return_value=_SANDBOX_OK):
        report: CycleReport = await hypothesize(
            "cycle-007",
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_writer=_fake_wiki_writer(tmp_path),
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    expected_total = report.ideation_spend_usd + report.codegen_spend_usd
    assert abs(report.total_spend_usd - expected_total) < 1e-9, (
        f"total={report.total_spend_usd} != ideation={report.ideation_spend_usd} "
        f"+ codegen={report.codegen_spend_usd}"
    )


# ---------------------------------------------------------------------------
# Test 8: db=None and bus=None — cycle still completes
# ---------------------------------------------------------------------------


async def test_no_db_no_bus_cycle_completes(tmp_path: Path) -> None:
    """With db=None and bus=None, registry inserts and bus publishes are
    skipped, but the cycle runs fully and returns a valid CycleReport."""
    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()

    with patch("research_orchestrator.workflow.run_in_sandbox", return_value=_SANDBOX_OK):
        report: CycleReport = await hypothesize(
            "cycle-008",
            db=None,
            bus=None,
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_writer=None,
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    assert not report.aborted
    assert len(report.outcomes) == 4
    for outcome in report.outcomes:
        assert (
            outcome.status == "passed"
        ), f"spec '{outcome.spec_name}' failed at '{outcome.stage}': {outcome.reason}"
        # No DB → no strategy_id assigned, wiki_writer=None → no wiki path
        assert outcome.strategy_id is None
        assert outcome.wiki_path is None


# ---------------------------------------------------------------------------
# Task 8 Test 9: wiki_root wiring — proposed files + daily log
# ---------------------------------------------------------------------------


async def test_cycle_writes_proposed_strategy_files_and_daily_log(tmp_path: Path) -> None:
    """wiki_root kwarg causes 4 proposed-strategy files and 1 daily-log file to be written.

    Frontmatter of each proposed file must contain all required 6b + 6c keys,
    and the filename stem must match the spec name.
    """
    import yaml

    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()
    wiki_root = tmp_path / "wiki"

    with patch("research_orchestrator.workflow.run_in_sandbox", return_value=_SANDBOX_OK):
        report: CycleReport = await hypothesize(
            "cycle-009",
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_root=wiki_root,
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    assert not report.aborted, f"cycle aborted: {report.abort_reason}"
    assert len(report.outcomes) == 4

    # 4 proposed-strategy files
    proposed_dir = wiki_root / "30-Strategies" / "proposed"
    assert proposed_dir.is_dir(), "proposed/ directory not created"
    proposed_files = list(proposed_dir.glob("*.md"))
    assert (
        len(proposed_files) == 4
    ), f"expected 4 files, got {len(proposed_files)}: {proposed_files}"

    # 1 daily log file
    daily_dir = wiki_root / "70-Daily"
    daily_files = list(daily_dir.glob("*.md"))
    assert len(daily_files) == 1, f"expected 1 daily log, got {len(daily_files)}: {daily_files}"

    # Check frontmatter of each proposed file
    required_6b_keys = {"title", "strategy-id", "venue", "module", "parameters"}
    required_6c_keys = {"generated_by", "cycle_id", "spec_sha256", "code_sha256"}
    required_keys = required_6b_keys | required_6c_keys

    for md_file in proposed_files:
        text = md_file.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines[0].strip() == "---", f"{md_file.name}: missing opening fence"
        close = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        fm = yaml.safe_load("\n".join(lines[1:close]))
        assert isinstance(fm, dict), f"{md_file.name}: frontmatter not a dict"

        missing = required_keys - set(fm.keys())
        assert not missing, f"{md_file.name}: missing frontmatter keys {sorted(missing)}"

        # Filename stem must match strategy-id
        assert (
            md_file.stem == fm["strategy-id"]
        ), f"{md_file.name}: stem '{md_file.stem}' != strategy-id '{fm['strategy-id']}'"

        # 6c fields must have non-empty values
        assert fm["generated_by"] == "orchestrator-6c"
        assert fm["cycle_id"] == "cycle-009"
        assert len(fm["spec_sha256"]) == 64  # SHA-256 hex is 64 chars
        assert len(fm["code_sha256"]) == 64


# ---------------------------------------------------------------------------
# Task 8 Test 10: two cycles same day → two daily-log sections
# ---------------------------------------------------------------------------


async def test_daily_log_appends_on_second_cycle_same_day(tmp_path: Path) -> None:
    """Two cycles with the same wiki_root on the same date produce two
    ``## Hypothesis Cycle`` sections in the daily log — not one overwritten."""
    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()
    wiki_root = tmp_path / "wiki"

    with patch("research_orchestrator.workflow.run_in_sandbox", return_value=_SANDBOX_OK):
        await hypothesize(
            "cycle-010a",
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_root=wiki_root,
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )
        # Second cycle — fresh tracker to avoid budget issues
        tracker2 = _make_spend_tracker(tmp_path / "tracker2")
        llm_client2 = _make_llm_client(settings, tracker2)
        await hypothesize(
            "cycle-010b",
            llm_client=llm_client2,
            spend_tracker=tracker2,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_root=wiki_root,
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    daily_files = list((wiki_root / "70-Daily").glob("*.md"))
    assert len(daily_files) == 1, "expected exactly 1 daily log file"
    content = daily_files[0].read_text(encoding="utf-8")

    cycle_a_count = content.count("## Hypothesis Cycle cycle-010a")
    cycle_b_count = content.count("## Hypothesis Cycle cycle-010b")
    assert cycle_a_count == 1, f"cycle-010a section count={cycle_a_count}, expected 1"
    assert cycle_b_count == 1, f"cycle-010b section count={cycle_b_count}, expected 1"


# ---------------------------------------------------------------------------
# Task 8 Test 11: round-trip via 6b loader
# ---------------------------------------------------------------------------


async def test_wiki_files_round_trip_via_6b_loader(tmp_path: Path) -> None:
    """Proposed-strategy files written by write_hypothesis parse cleanly
    via strategy_registry.wiki_loader._split_frontmatter + _parse_frontmatter
    + _validate_keys (the shape-only subset, without the module import check).
    """
    from strategy_registry.wiki_loader import _parse_frontmatter, _split_frontmatter, _validate_keys

    settings = _make_settings(tmp_path)
    tracker = _make_spend_tracker(tmp_path)
    llm_client = _make_llm_client(settings, tracker)
    context_builder = _make_context_builder()
    wiki_root = tmp_path / "wiki"

    with patch("research_orchestrator.workflow.run_in_sandbox", return_value=_SANDBOX_OK):
        report: CycleReport = await hypothesize(
            "cycle-011",
            llm_client=llm_client,
            spend_tracker=tracker,
            context_builder=context_builder,
            settings=settings,
            backtest_runner=_fake_backtest_runner,
            wiki_root=wiki_root,
            tick_source_factory=_tick_source_factory,
            time_range=_TIME_RANGE,
        )

    assert not report.aborted

    proposed_dir = wiki_root / "30-Strategies" / "proposed"
    md_files = list(proposed_dir.glob("*.md"))
    assert md_files, "no proposed files written"

    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        # _split_frontmatter → _parse_frontmatter → _validate_keys must
        # all succeed without raising StrategyLoadError.
        raw_yaml = _split_frontmatter(text)
        frontmatter = _parse_frontmatter(raw_yaml)
        _validate_keys(frontmatter)  # raises StrategyLoadError if shape is wrong

        # Additionally verify the strategy-id / filename invariant
        assert (
            frontmatter["strategy-id"] == md_file.stem
        ), f"strategy-id '{frontmatter['strategy-id']}' != filename stem '{md_file.stem}'"

"""Unit tests for research_orchestrator.wiki_writer.

These tests are offline (no DB, no Redis, no disk beyond ``tmp_path``). They
operate on a copy of the reference strategy wiki file and exercise the
round-trip + idempotency contracts described in Phase 6b.5.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from research_orchestrator.wiki_writer import write_backtest_results

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[3]
_REFERENCE_WIKI_PATH = _REPO_ROOT / "wiki" / "30-Strategies" / "mean-reversion-ref.md"


def _stub_metrics() -> dict[str, object]:
    return {
        "total_pnl_gbp": Decimal("12.3456"),
        "win_rate": 0.6234,
        "n_trades": 42,
        "max_drawdown_gbp": Decimal("-3.2100"),
        "n_ticks_consumed": 300,
        "started_at": datetime(2026, 4, 21, 9, 0, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 4, 21, 9, 5, 0, tzinfo=UTC),
        "sharpe": 1.8765,
    }


def _copy_reference(tmp_path: Path) -> Path:
    dst = tmp_path / "mean-reversion-ref.md"
    shutil.copyfile(_REFERENCE_WIKI_PATH, dst)
    return dst


def test_write_backtest_results_roundtrip(tmp_path: Path) -> None:
    """After write, the file must still be loadable and contain the new
    metrics under ``## Backtest Results`` while preserving the other body
    sections verbatim.
    """
    wiki_path = _copy_reference(tmp_path)
    original = wiki_path.read_text(encoding="utf-8")

    run_ended_at = datetime(2026, 4, 21, 9, 5, 0, tzinfo=UTC)
    write_backtest_results(wiki_path, _stub_metrics(), run_ended_at)

    updated = wiki_path.read_text(encoding="utf-8")

    # Frontmatter: updated: field reflects run_ended_at date (YYYY-MM-DD).
    assert "updated: 2026-04-21" in updated

    # strategy-id + other frontmatter keys preserved.
    assert "strategy-id: mean-reversion-ref" in updated
    assert "module: backtest_engine.strategies.mean_reversion" in updated

    # Body: Backtest Results block replaced.
    assert "_pending_" not in updated.split("## Backtest Results", 1)[1].split("## ", 1)[0]
    assert "Trades: 42" in updated
    assert "Sharpe:" in updated
    assert "Total P&L:" in updated
    assert "Max drawdown:" in updated
    assert "Ticks: 300" in updated
    assert "Win rate:" in updated
    assert "Period:" in updated

    # Body preservation: sections above and below Backtest Results unchanged.
    before_mid = original.split("## Hypothesis", 1)[1]
    before_hypothesis = before_mid.split("## Backtest Results", 1)[0]
    after_mid = updated.split("## Hypothesis", 1)[1]
    after_hypothesis = after_mid.split("## Backtest Results", 1)[0]
    assert before_hypothesis == after_hypothesis

    paper_and_below_before = original.split("## Paper Trading Results", 1)[1]
    paper_and_below_after = updated.split("## Paper Trading Results", 1)[1]
    assert paper_and_below_before == paper_and_below_after

    # Loadable by wiki_loader shape: starts with '---' fence and ends with one.
    assert updated.startswith("---\n")
    # Frontmatter key order preserved: title is still first.
    assert updated.splitlines()[1].startswith("title:")


def test_write_backtest_results_idempotent(tmp_path: Path) -> None:
    """Two writes with identical metrics + identical run_ended_at must
    produce byte-identical output.
    """
    wiki_path = _copy_reference(tmp_path)
    run_ended_at = datetime(2026, 4, 21, 9, 5, 0, tzinfo=UTC)

    write_backtest_results(wiki_path, _stub_metrics(), run_ended_at)
    first = wiki_path.read_bytes()

    write_backtest_results(wiki_path, _stub_metrics(), run_ended_at)
    second = wiki_path.read_bytes()

    assert first == second


def test_write_backtest_results_updates_only_updated_field(tmp_path: Path) -> None:
    """A second call with a later ``run_ended_at`` but identical metrics
    must only change the ``updated:`` line; everything else byte-identical.
    """
    wiki_path = _copy_reference(tmp_path)

    write_backtest_results(wiki_path, _stub_metrics(), datetime(2026, 4, 21, tzinfo=UTC))
    first = wiki_path.read_text(encoding="utf-8")

    write_backtest_results(wiki_path, _stub_metrics(), datetime(2026, 4, 22, tzinfo=UTC))
    second = wiki_path.read_text(encoding="utf-8")

    # Only the updated: line differs.
    first_lines = first.splitlines()
    second_lines = second.splitlines()
    assert len(first_lines) == len(second_lines)
    diffs = [i for i, (a, b) in enumerate(zip(first_lines, second_lines, strict=True)) if a != b]
    assert len(diffs) == 1
    assert first_lines[diffs[0]].startswith("updated:")
    assert second_lines[diffs[0]] == "updated: 2026-04-22"

"""Tests for the research-orchestrator CLI commands (Phase 6c Task 7).

All tests are offline — no Postgres, no Redis, no live xAI calls.

Two commands exercised:
- ``hypothesize --dry-run``: expect stdout with 4 spec names + ``def compute_signal``.
- ``spend-today``: expect parseable ``Spend today: $X.XX / $Y.YY cap`` line.

The ``--dry-run`` flag must NOT instantiate ``algobet_common.Database``; the
test verifies this via monkeypatching the Database constructor with an
assertion-raising stub.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from research_orchestrator.__main__ import app
from typer.testing import CliRunner

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Set required env vars for mock mode."""
    monkeypatch.setenv("XAI_API_KEY", "mock")
    monkeypatch.setenv("XAI_CASSETTE_DIR", str(_CASSETTE_DIR))
    # Point spend DB to an isolated tmp location via env var
    # (the CLI uses a hardcoded default; we patch the module instead — see below)


# ---------------------------------------------------------------------------
# Test 1: --dry-run prints spec names + generated code, no DB writes
# ---------------------------------------------------------------------------


def test_dry_run_prints_specs_and_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``hypothesize --dry-run`` must print all 4 spec names and at least one
    ``def compute_signal`` line without touching the database."""
    _set_env(monkeypatch, tmp_path)

    # Guard: Database must never be instantiated during dry-run.
    def _db_forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Database was instantiated during --dry-run; this is forbidden.")

    monkeypatch.setattr(
        "research_orchestrator.__main__.Database",
        _db_forbidden,
    )

    # Redirect the spend DB to a tmp path so the test is isolated.
    spend_db = tmp_path / "spend.db"
    monkeypatch.setattr(
        "research_orchestrator.__main__._default_spend_db_path",
        spend_db,
    )

    runner = CliRunner()
    result = runner.invoke(app, ["hypothesize", "--dry-run"])

    assert result.exit_code == 0, f"CLI exited {result.exit_code}:\n{result.output}"

    output = result.output
    for name in _SPEC_NAMES:
        assert name in output, f"Expected spec name '{name}' in output:\n{output}"

    assert "def compute_signal" in output, f"Expected 'def compute_signal' in output:\n{output}"


# ---------------------------------------------------------------------------
# Test 2: spend-today prints a parseable line
# ---------------------------------------------------------------------------


def test_spend_today_prints_parseable_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``spend-today`` must print a line matching ``Spend today: $X.XX / $Y.YY cap``."""
    _set_env(monkeypatch, tmp_path)

    spend_db = tmp_path / "spend.db"
    monkeypatch.setattr(
        "research_orchestrator.__main__._default_spend_db_path",
        spend_db,
    )

    runner = CliRunner()
    result = runner.invoke(app, ["spend-today"])

    assert result.exit_code == 0, f"CLI exited {result.exit_code}:\n{result.output}"

    pattern = r"Spend today: \$\d+\.\d{2} / \$\d+\.\d{2} cap"
    assert re.search(
        pattern, result.output
    ), f"Expected line matching '{pattern}' in output:\n{result.output}"

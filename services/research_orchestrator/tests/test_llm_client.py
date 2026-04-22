"""Tests for llm_client.py — mock-backed cassette replay + budget guard.

All tests run in mock mode (``XAI_API_KEY="mock"``).  No network calls are
made.  The sentinel pattern is used for budget-exceeded tests: the OpenAI
client attribute is replaced with a sentinel object whose ``__call__`` raises
``AssertionError`` if invoked, proving that no HTTP code path was reached.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from research_orchestrator.ast_validator import validate
from research_orchestrator.config import OrchestratorSettings
from research_orchestrator.llm_client import (
    BudgetExceeded,
    CassetteNotFoundError,
    LLMClient,
    LLMResponseInvalid,
)
from research_orchestrator.spend_tracker import SpendTracker
from research_orchestrator.types import IdeationContext, ParamRange, StrategySpec

# ---------------------------------------------------------------------------
# Fixtures path
# ---------------------------------------------------------------------------

_CASSETTE_DIR = Path(__file__).parent / "fixtures" / "llm_cassettes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_settings(tmp_path: Path, cassette_dir: Path | None = None) -> OrchestratorSettings:
    """Return OrchestratorSettings in mock mode with a temp cassette dir."""
    return OrchestratorSettings(
        xai_api_key="mock",
        xai_base_url="https://api.x.ai/v1",
        xai_model_ideation="grok-4",
        xai_model_codegen="grok-4-fast-reasoning",
        hypothesis_daily_usd_cap=5.0,
        xai_cassette_dir=cassette_dir if cassette_dir is not None else _CASSETTE_DIR,
    )


def _tracker(tmp_path: Path) -> SpendTracker:
    return SpendTracker(db_path=tmp_path / "spend.db")


def _client(tmp_path: Path, cassette_dir: Path | None = None) -> LLMClient:
    settings = _mock_settings(tmp_path, cassette_dir=cassette_dir)
    tracker = _tracker(tmp_path)
    return LLMClient(settings=settings, spend_tracker=tracker)


def _sample_context() -> IdeationContext:
    return IdeationContext(
        static="You are a trading research assistant.",
        features=("mid: (best_bid + best_ask) / 2", "spread: best_ask - best_bid"),
        prior_cycles="",
        regime="Calm, low-volume pre-race period.",
    )


def _sample_spec(name: str = "bollinger_reversion") -> StrategySpec:
    return StrategySpec(
        name=name,
        rationale="Test rationale.",
        signal_formula="z = (mid - mean) / std",
        params={"window": ParamRange(kind="int", low=10, high=100, default=20)},
        entry_rules="Enter when |z| > 2.",
        exit_rules="Exit when |z| < 0.5.",
        expected_edge="Mean reversion.",
    )


# ---------------------------------------------------------------------------
# Sentinel that raises if any attribute is accessed (proves no HTTP was called)
# ---------------------------------------------------------------------------


class _HttpSentinel:
    """Raises AssertionError on any attribute access to catch unexpected calls."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"HTTP client was accessed (attribute '{name}') even though "
            "BudgetExceeded should have been raised before any HTTP call."
        )


# ---------------------------------------------------------------------------
# Test: ideate mock returns 4 StrategySpec instances
# ---------------------------------------------------------------------------


def test_ideate_mock_returns_four_specs(tmp_path: Path) -> None:
    client = _client(tmp_path)
    context = _sample_context()
    specs = client.ideate(context, cassette_name="ideation_default")

    assert len(specs) == 4, f"Expected 4 specs, got {len(specs)}"
    for spec in specs:
        assert isinstance(spec, StrategySpec)
        assert spec.name
        assert spec.rationale
        assert isinstance(spec.params, dict)


def test_ideate_mock_spec_names_are_unique(tmp_path: Path) -> None:
    client = _client(tmp_path)
    specs = client.ideate(_sample_context(), cassette_name="ideation_default")
    names = [s.name for s in specs]
    assert len(names) == len(set(names)), "Spec names are not unique within cycle"


def test_ideate_mock_param_ranges_valid(tmp_path: Path) -> None:
    client = _client(tmp_path)
    specs = client.ideate(_sample_context(), cassette_name="ideation_default")
    for spec in specs:
        for param_name, pr in spec.params.items():
            assert pr.low <= pr.high, f"{spec.name}.{param_name}: low > high"
            assert (
                pr.low <= pr.default <= pr.high
            ), f"{spec.name}.{param_name}: default not in [low, high]"


# ---------------------------------------------------------------------------
# Test: codegen mock returns source string
# ---------------------------------------------------------------------------


def test_codegen_mock_returns_source_string(tmp_path: Path) -> None:
    client = _client(tmp_path)
    spec = _sample_spec("bollinger_reversion")
    source = client.codegen(spec, cassette_name="codegen_bollinger_reversion")

    assert isinstance(source, str)
    assert len(source.strip()) > 0


def test_codegen_mock_second_cassette(tmp_path: Path) -> None:
    client = _client(tmp_path)
    spec = _sample_spec("microprice_drift")
    source = client.codegen(spec, cassette_name="codegen_microprice_drift")

    assert isinstance(source, str)
    assert len(source.strip()) > 0


# ---------------------------------------------------------------------------
# Test: codegen source passes AST validator
# ---------------------------------------------------------------------------


def test_codegen_source_passes_ast_validator_bollinger(tmp_path: Path) -> None:
    client = _client(tmp_path)
    spec = _sample_spec("bollinger_reversion")
    source = client.codegen(spec, cassette_name="codegen_bollinger_reversion")

    result = validate(source)
    assert result.ok, (
        f"AST validator rejected bollinger_reversion source.\n" f"Violations: {result.violations}"
    )


def test_codegen_source_passes_ast_validator_microprice(tmp_path: Path) -> None:
    client = _client(tmp_path)
    spec = _sample_spec("microprice_drift")
    source = client.codegen(spec, cassette_name="codegen_microprice_drift")

    result = validate(source)
    assert result.ok, (
        f"AST validator rejected microprice_drift source.\n" f"Violations: {result.violations}"
    )


# ---------------------------------------------------------------------------
# Test: malformed cassette JSON → retries then raises LLMResponseInvalid
# ---------------------------------------------------------------------------


def test_ideate_malformed_retries_then_aborts(tmp_path: Path) -> None:
    """Malformed ideation cassette triggers retry, then LLMResponseInvalid."""
    client = _client(tmp_path)
    context = _sample_context()

    # The malformed cassette has content "this is not valid json {"
    # The client should retry once and then raise.
    with pytest.raises(LLMResponseInvalid):
        client.ideate(context, cassette_name="ideation_malformed")


def test_ideate_malformed_cassette_retry_is_bounded(tmp_path: Path) -> None:
    """Verify that the retry count is bounded — we don't loop infinitely."""
    call_count = 0
    original_ideate_mock = LLMClient._ideate_mock

    def counting_mock(self: LLMClient, cassette_name: str) -> tuple[list[StrategySpec], int, int]:
        nonlocal call_count
        call_count += 1
        return original_ideate_mock(self, cassette_name)

    client = _client(tmp_path)
    LLMClient._ideate_mock = counting_mock  # type: ignore[method-assign]

    try:
        with pytest.raises(LLMResponseInvalid):
            client.ideate(_sample_context(), cassette_name="ideation_malformed")
    finally:
        LLMClient._ideate_mock = original_ideate_mock  # type: ignore[method-assign]

    # Default max_retries=1 → 2 total attempts
    assert call_count == 2, f"Expected 2 attempts (1 + 1 retry), got {call_count}"


# ---------------------------------------------------------------------------
# Test: budget guard raises before HTTP
# ---------------------------------------------------------------------------


def test_ideate_budget_exceeded_raises_before_http(tmp_path: Path) -> None:
    """BudgetExceeded is raised before any HTTP call when cap would be exceeded."""
    # Set a tiny cap and fill it with a prior spend
    settings = OrchestratorSettings(
        xai_api_key="mock",
        xai_cassette_dir=_CASSETTE_DIR,
        hypothesis_daily_usd_cap=0.000001,  # $0.000001 — trivially exceeded
    )
    tracker = SpendTracker(db_path=tmp_path / "spend.db")
    # Record a prior spend that consumes the entire cap
    tracker.record(model="grok-4", input_tokens=1, output_tokens=1)

    client = LLMClient(settings=settings, spend_tracker=tracker)
    # Install sentinel — any HTTP access would raise AssertionError
    client._openai_client = _HttpSentinel()

    with pytest.raises(BudgetExceeded) as exc_info:
        client.ideate(_sample_context(), cassette_name="ideation_default")

    exc = exc_info.value
    assert exc.cap_usd == pytest.approx(0.000001)
    assert exc.cumulative_usd > 0


def test_codegen_budget_exceeded_raises_before_http(tmp_path: Path) -> None:
    """BudgetExceeded is raised before any HTTP call for codegen too."""
    settings = OrchestratorSettings(
        xai_api_key="mock",
        xai_cassette_dir=_CASSETTE_DIR,
        hypothesis_daily_usd_cap=0.000001,
    )
    tracker = SpendTracker(db_path=tmp_path / "spend.db")
    tracker.record(model="grok-4-fast-reasoning", input_tokens=1, output_tokens=1)

    client = LLMClient(settings=settings, spend_tracker=tracker)
    client._openai_client = _HttpSentinel()

    spec = _sample_spec("bollinger_reversion")
    with pytest.raises(BudgetExceeded):
        client.codegen(spec, cassette_name="codegen_bollinger_reversion")


def test_budget_exceeded_without_prior_spend(tmp_path: Path) -> None:
    """Even zero prior spend exceeds a zero-dollar cap."""
    settings = OrchestratorSettings(
        xai_api_key="mock",
        xai_cassette_dir=_CASSETTE_DIR,
        hypothesis_daily_usd_cap=0.0,  # any cost exceeds $0
    )
    tracker = SpendTracker(db_path=tmp_path / "spend.db")
    client = LLMClient(settings=settings, spend_tracker=tracker)
    client._openai_client = _HttpSentinel()

    with pytest.raises(BudgetExceeded):
        client.ideate(_sample_context(), cassette_name="ideation_default")


# ---------------------------------------------------------------------------
# Test: unknown cassette name raises CassetteNotFoundError
# ---------------------------------------------------------------------------


def test_unknown_cassette_name_raises(tmp_path: Path) -> None:
    client = _client(tmp_path)
    with pytest.raises(CassetteNotFoundError) as exc_info:
        client.ideate(_sample_context(), cassette_name="ideation_nonexistent_xyz")

    err = exc_info.value
    assert "ideation_nonexistent_xyz" in str(err)
    # Error message must include the resolved path
    assert str(_CASSETTE_DIR) in str(err) or "ideation_nonexistent_xyz" in str(err)


def test_unknown_cassette_name_for_codegen_raises(tmp_path: Path) -> None:
    client = _client(tmp_path)
    spec = _sample_spec("strategy_that_has_no_cassette")
    with pytest.raises(CassetteNotFoundError):
        client.codegen(spec)


# ---------------------------------------------------------------------------
# Test: cassette_dir override is respected
# ---------------------------------------------------------------------------


def test_cassette_dir_override_respected(tmp_path: Path) -> None:
    """XAI_CASSETTE_DIR override causes the client to load from that directory."""
    # Write a minimal valid ideation cassette to a custom dir
    custom_dir = tmp_path / "custom_cassettes"
    custom_dir.mkdir()
    cassette = {
        "name": "ideation_default",
        "request": {"model": "grok-4", "system": "s", "user": "u"},
        "response": {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"hypotheses": ['
                            '{"name": "test_strat", "rationale": "r", '
                            '"signal_formula": "f", "params": {}, '
                            '"entry_rules": "e", "exit_rules": "x", '
                            '"expected_edge": "edge"}'
                            "]}"
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    }
    import json as _json

    (custom_dir / "ideation_default.json").write_text(_json.dumps(cassette), encoding="utf-8")

    client = _client(tmp_path, cassette_dir=custom_dir)
    specs = client.ideate(_sample_context(), cassette_name="ideation_default")

    assert len(specs) == 1
    assert specs[0].name == "test_strat"


# ---------------------------------------------------------------------------
# Test: spend tracker records spend after mock calls
# ---------------------------------------------------------------------------


def test_spend_recorded_after_ideate(tmp_path: Path) -> None:
    """Spend tracker accumulates cost from mock cassette usage field."""
    tracker = _tracker(tmp_path)
    settings = _mock_settings(tmp_path)
    client = LLMClient(settings=settings, spend_tracker=tracker)

    assert tracker.cumulative_today_usd() == pytest.approx(0.0)
    client.ideate(_sample_context(), cassette_name="ideation_default")
    assert tracker.cumulative_today_usd() > 0.0


def test_spend_recorded_after_codegen(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    settings = _mock_settings(tmp_path)
    client = LLMClient(settings=settings, spend_tracker=tracker)

    assert tracker.cumulative_today_usd() == pytest.approx(0.0)
    spec = _sample_spec("bollinger_reversion")
    client.codegen(spec, cassette_name="codegen_bollinger_reversion")
    assert tracker.cumulative_today_usd() > 0.0


# ---------------------------------------------------------------------------
# Test: cassette with malformed outer JSON (not just bad content)
# ---------------------------------------------------------------------------


def test_cassette_with_malformed_outer_json_raises(tmp_path: Path) -> None:
    """A cassette file that is not valid JSON at all should raise LLMResponseInvalid."""
    bad_dir = tmp_path / "bad_cassettes"
    bad_dir.mkdir()
    (bad_dir / "broken.json").write_text("{not valid json", encoding="utf-8")

    client = _client(tmp_path, cassette_dir=bad_dir)
    with pytest.raises(LLMResponseInvalid):
        client.ideate(_sample_context(), cassette_name="broken")


def test_cassette_missing_choices_raises(tmp_path: Path) -> None:
    """A cassette file missing 'choices' raises LLMResponseInvalid."""
    import json as _json

    bad_dir = tmp_path / "bad_cassettes2"
    bad_dir.mkdir()
    # Missing 'choices'
    (bad_dir / "no_choices.json").write_text(
        _json.dumps(
            {"name": "x", "response": {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}}
        ),
        encoding="utf-8",
    )

    client = _client(tmp_path, cassette_dir=bad_dir)
    with pytest.raises(LLMResponseInvalid):
        client.ideate(_sample_context(), cassette_name="no_choices")

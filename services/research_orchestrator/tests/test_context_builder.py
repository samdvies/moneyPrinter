"""Tests for the 4-layer ContextBuilder (Phase 6c Task 5).

All tests operate without a live Postgres connection.  DB dependencies are
injected as async stubs that return synthetic rows.

Test matrix
-----------
- test_build_offline_returns_populated_static_and_features
    No DB; static non-empty, features tuple has 9 entries.
- test_build_empty_registry_prior_cycles_empty
    registry_repo stub returns []; prior_cycles == "".
- test_build_below_five_cycles_prior_cycles_empty
    registry_repo stub returns 3 rows; prior_cycles == "".
- test_build_with_ten_cycles_top_k_bottom_k
    stub returns 10 rows with varied sharpes; top-K names present, bottom-K
    names present, ordering correct.
- test_build_regime_query_rendered
    timescale_query stub returns synthetic aggregate; rendered string has
    expected fields.
- test_ideation_prompt_under_budget
    len(ideation_system.md) < 8000 chars.
- test_codegen_prompt_under_budget
    len(codegen_system.md) < 12000 chars.
- test_strategy_template_has_required_frontmatter_fields
    strategy_template.md contains required YAML frontmatter keys.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from research_orchestrator.context_builder import ContextBuilder, ContextBuilderConfig
from research_orchestrator.features import FEATURES

_RegistryStub = Callable[[int, int], Awaitable[list[dict[str, Any]]]]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parents[1] / "src" / "research_orchestrator" / "prompts"


async def _empty_registry(lookback_days: int, limit: int) -> list[dict[str, Any]]:
    return []


async def _three_row_registry(lookback_days: int, limit: int) -> list[dict[str, Any]]:
    return [{"slug": f"strategy-{i}", "sharpe": float(i), "status": "hypothesis"} for i in range(3)]


def _make_ten_row_registry() -> tuple[_RegistryStub, list[dict[str, Any]]]:
    """Produce a registry stub returning 10 rows with sharpes 0.0..9.0."""
    sharpes = [float(i) for i in range(10)]
    rows: list[dict[str, Any]] = [
        {"slug": f"strat-{i:02d}", "sharpe": sharpes[i], "status": "hypothesis"} for i in range(10)
    ]

    async def _stub(lookback_days: int, limit: int) -> list[dict[str, Any]]:
        return rows

    return _stub, rows


async def _regime_stub(lookback_days: int) -> dict[str, Any]:
    return {
        "median_spread": 0.0250,
        "median_bid_depth": 142.50,
        "median_ask_depth": 98.30,
        "sport_rows": [
            {"sport": "football", "count": 1500},
            {"sport": "horse_racing", "count": 800},
        ],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> ContextBuilderConfig:
    return ContextBuilderConfig(prompts_dir=_PROMPTS_DIR)


# ---------------------------------------------------------------------------
# Tests: core build() behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_offline_returns_populated_static_and_features(
    config: ContextBuilderConfig,
) -> None:
    """Offline mode: static non-empty, features tuple has 9 entries."""
    builder = ContextBuilder(config=config)
    ctx = await builder.build("cycle-001")

    assert isinstance(ctx.static, str)
    assert len(ctx.static) > 100, "static prompt should be non-trivial"
    assert len(ctx.features) == 9
    # Each feature line is a non-empty string
    for line in ctx.features:
        assert isinstance(line, str) and line.strip()


@pytest.mark.asyncio
async def test_build_empty_registry_prior_cycles_empty(
    config: ContextBuilderConfig,
) -> None:
    """Empty registry → prior_cycles is empty string."""
    builder = ContextBuilder(registry_repo=_empty_registry, config=config)
    ctx = await builder.build("cycle-002")
    assert ctx.prior_cycles == ""


@pytest.mark.asyncio
async def test_build_below_five_cycles_prior_cycles_empty(
    config: ContextBuilderConfig,
) -> None:
    """3 rows < threshold (5) → prior_cycles is empty string."""
    builder = ContextBuilder(registry_repo=_three_row_registry, config=config)
    ctx = await builder.build("cycle-003")
    assert ctx.prior_cycles == ""


@pytest.mark.asyncio
async def test_build_with_ten_cycles_top_k_bottom_k(
    config: ContextBuilderConfig,
) -> None:
    """10 rows → prior_cycles contains top-K and bottom-K in correct order."""
    stub, rows = _make_ten_row_registry()
    # Use default K=3
    builder = ContextBuilder(registry_repo=stub, config=config)
    ctx = await builder.build("cycle-004")

    pc = ctx.prior_cycles
    assert pc != "", "prior_cycles must be populated with 10 rows"

    # Top 3 by Sharpe are strat-09 (9.0), strat-08 (8.0), strat-07 (7.0)
    assert "strat-09" in pc
    assert "strat-08" in pc
    assert "strat-07" in pc

    # Bottom 3 by Sharpe are strat-00 (0.0), strat-01 (1.0), strat-02 (2.0)
    assert "strat-00" in pc
    assert "strat-01" in pc
    assert "strat-02" in pc

    # Ordering: "Top 3 by Sharpe:" must precede "Bottom 3 by Sharpe:"
    assert pc.index("Top 3 by Sharpe:") < pc.index("Bottom 3 by Sharpe:")

    # Verify the top entry has higher Sharpe listed before next
    top_block_start = pc.index("Top 3 by Sharpe:")
    bottom_block_start = pc.index("Bottom 3 by Sharpe:")
    top_block = pc[top_block_start:bottom_block_start]
    assert top_block.index("strat-09") < top_block.index("strat-08")
    assert top_block.index("strat-08") < top_block.index("strat-07")


@pytest.mark.asyncio
async def test_build_regime_query_rendered(
    config: ContextBuilderConfig,
) -> None:
    """Regime stub → rendered string has all expected fields."""
    builder = ContextBuilder(timescale_query=_regime_stub, config=config)
    ctx = await builder.build("cycle-005")

    regime = ctx.regime
    assert "Regime (last 7 days):" in regime
    assert "Median spread:" in regime
    assert "Median best_bid_depth:" in regime
    assert "Median best_ask_depth:" in regime
    assert "football" in regime
    assert "horse_racing" in regime
    # Numeric values
    assert "0.0250" in regime
    assert "142.50" in regime
    assert "98.30" in regime


@pytest.mark.asyncio
async def test_build_regime_none_when_no_query(
    config: ContextBuilderConfig,
) -> None:
    """No timescale_query → regime is empty string."""
    builder = ContextBuilder(config=config)
    ctx = await builder.build("cycle-006")
    assert ctx.regime == ""


# ---------------------------------------------------------------------------
# Tests: both DB layers populated simultaneously
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_all_layers_populated(
    config: ContextBuilderConfig,
) -> None:
    """Smoke test: all 4 layers populated when stubs are injected."""
    stub, _ = _make_ten_row_registry()
    builder = ContextBuilder(
        registry_repo=stub,
        timescale_query=_regime_stub,
        config=config,
    )
    ctx = await builder.build("cycle-007")

    assert ctx.static
    assert len(ctx.features) == 9
    assert ctx.prior_cycles != ""
    assert ctx.regime != ""


# ---------------------------------------------------------------------------
# Tests: custom K configuration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_custom_k_respected() -> None:
    """ContextBuilderConfig(prior_cycle_k=2) → only 2 top and 2 bottom entries."""
    stub, _ = _make_ten_row_registry()
    cfg = ContextBuilderConfig(prior_cycle_k=2, prompts_dir=_PROMPTS_DIR)
    builder = ContextBuilder(registry_repo=stub, config=cfg)
    ctx = await builder.build("cycle-008")

    pc = ctx.prior_cycles
    assert "Top 2 by Sharpe:" in pc
    assert "Bottom 2 by Sharpe:" in pc
    # Top 2: strat-09, strat-08
    assert "strat-09" in pc
    assert "strat-08" in pc
    # strat-07 should NOT be in top block with k=2
    top_block_end = pc.index("Bottom 2 by Sharpe:")
    top_block = pc[:top_block_end]
    assert "strat-07" not in top_block


# ---------------------------------------------------------------------------
# Tests: registry exception handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_exception_returns_empty_prior_cycles(
    config: ContextBuilderConfig,
) -> None:
    """Registry raises → prior_cycles gracefully returns empty string."""

    async def _failing_registry(lookback_days: int, limit: int) -> list[dict[str, Any]]:
        raise RuntimeError("DB connection refused")

    builder = ContextBuilder(registry_repo=_failing_registry, config=config)
    ctx = await builder.build("cycle-009")
    assert ctx.prior_cycles == ""


@pytest.mark.asyncio
async def test_timescale_exception_returns_empty_regime(
    config: ContextBuilderConfig,
) -> None:
    """Timescale raises → regime gracefully returns empty string."""

    async def _failing_timescale(lookback_days: int) -> dict[str, Any]:
        raise RuntimeError("connection timeout")

    builder = ContextBuilder(timescale_query=_failing_timescale, config=config)
    ctx = await builder.build("cycle-010")
    assert ctx.regime == ""


# ---------------------------------------------------------------------------
# Tests: prompt file budgets and content
# ---------------------------------------------------------------------------


def test_ideation_prompt_under_budget() -> None:
    """ideation_system.md must be under 8000 chars."""
    path = _PROMPTS_DIR / "ideation_system.md"
    content = path.read_text(encoding="utf-8")
    assert len(content) < 8000, f"ideation_system.md is {len(content)} chars (budget: 8000)"


def test_codegen_prompt_under_budget() -> None:
    """codegen_system.md must be under 12000 chars."""
    path = _PROMPTS_DIR / "codegen_system.md"
    content = path.read_text(encoding="utf-8")
    assert len(content) < 12000, f"codegen_system.md is {len(content)} chars (budget: 12000)"


def test_strategy_template_has_required_frontmatter_fields() -> None:
    """strategy_template.md must contain all required YAML frontmatter keys."""
    path = _PROMPTS_DIR / "strategy_template.md"
    content = path.read_text(encoding="utf-8")

    required_fields = [
        "title:",
        "type:",
        "strategy-id:",
        "venue:",
        "status:",
        "generated_by:",
        "cycle_id:",
        "spec_sha256:",
        "code_sha256:",
        "parameters:",
        "tags:",
    ]
    for field_key in required_fields:
        assert (
            field_key in content
        ), f"strategy_template.md is missing frontmatter field '{field_key}'"


# ---------------------------------------------------------------------------
# Tests: features module consistency
# ---------------------------------------------------------------------------


def test_features_count() -> None:
    """FEATURES tuple must have exactly 9 entries."""
    assert len(FEATURES) == 9


def test_render_feature_lines_count() -> None:
    """render_feature_lines() must return 9 strings."""
    from research_orchestrator.features import render_feature_lines

    lines = render_feature_lines()
    assert len(lines) == 9


def test_render_feature_lines_format() -> None:
    """Each rendered line must contain the feature name and the separator '—'."""
    from research_orchestrator.features import render_feature_lines

    lines = render_feature_lines()
    for line in lines:
        assert " — " in line, f"Line missing ' — ' separator: {line!r}"


def test_feature_names_unique() -> None:
    """All feature names in FEATURES must be unique."""
    names = [f.name for f in FEATURES]
    assert len(names) == len(set(names)), "Duplicate feature names found"


def test_expected_feature_names_present() -> None:
    """The 9 seed feature names must all be present in FEATURES."""
    expected = {
        "best_bid",
        "best_ask",
        "mid",
        "spread",
        "book_imbalance",
        "microprice",
        "recent_mid_velocity",
        "best_bid_depth",
        "best_ask_depth",
    }
    actual = {f.name for f in FEATURES}
    assert expected == actual, f"Unexpected features: {actual.symmetric_difference(expected)}"


# ---------------------------------------------------------------------------
# Tests: IdeationContext contract unchanged
# ---------------------------------------------------------------------------


def test_ideation_context_fields() -> None:
    """IdeationContext has the expected 4 fields with the correct types."""
    from research_orchestrator.types import IdeationContext

    ctx = IdeationContext(
        static="hello",
        features=("a", "b"),
        prior_cycles="",
        regime="",
    )
    assert ctx.static == "hello"
    assert ctx.features == ("a", "b")
    assert ctx.prior_cycles == ""
    assert ctx.regime == ""

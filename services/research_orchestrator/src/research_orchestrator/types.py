"""Shared data contracts for Phase 6c hypothesis generation.

These dataclasses are the boundary types between the LLM pipeline
(llm_client.py), the context builder (context_builder.py), and the
orchestration layer (workflow.py).

Design: frozen dataclasses (not pydantic) — they cross from LLM-derived JSON
to in-process Python; pydantic overhead is unnecessary at this boundary.

Note on mutable fields: ``StrategySpec.params`` is typed as
``dict[str, ParamRange]``.  Frozen dataclasses still allow mutation of dict
values.  This is accepted at the project-internal boundary — callers must not
mutate the dict after construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ParamRange:
    """Bounded parameter range with a default.

    Parameters
    ----------
    kind:
        Whether the parameter is an integer or a float.
    low:
        Inclusive lower bound of the search space.
    high:
        Inclusive upper bound of the search space.
    default:
        Default / initial value used when no tuning has occurred yet.
    """

    kind: Literal["int", "float"]
    low: float
    high: float
    default: float


@dataclass(frozen=True)
class StrategySpec:
    """A single hypothesis produced by the LLM ideation stage.

    All fields are required; the LLM response is validated against this
    shape before the instance is constructed.

    Parameters
    ----------
    name:
        Snake_case identifier, unique within a generation cycle.
    rationale:
        1-3 sentence human-readable explanation.
    signal_formula:
        Human-readable pseudocode describing the signal computation.
    params:
        Named parameter ranges. Keys are snake_case parameter names.
    entry_rules:
        When to enter a position (plain text).
    exit_rules:
        When to exit a position (plain text).
    expected_edge:
        Brief statement of the anticipated alpha source.
    """

    name: str
    rationale: str
    signal_formula: str
    params: dict[str, ParamRange]
    entry_rules: str
    exit_rules: str
    expected_edge: str


@dataclass(frozen=True)
class IdeationContext:
    """Assembled context fed to the LLM ideation prompt.

    Parameters
    ----------
    static:
        Layer 1 — static system preamble loaded from
        ``prompts/ideation_system.md``.
    features:
        Layer 2 — one-liner per available feature (e.g. ``"mid: (best_bid +
        best_ask) / 2"``).  Passed as a tuple to preserve immutability.
    prior_cycles:
        Layer 3 — summary of prior generation cycles (top/bottom by Sharpe),
        or empty string if fewer than 5 prior cycles exist.
    regime:
        Layer 4 — summary of recent market regime statistics.
    """

    static: str
    features: tuple[str, ...]
    prior_cycles: str
    regime: str


# ---------------------------------------------------------------------------
# Cycle report types (Phase 6c Task 6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpecOutcome:
    """Outcome record for a single strategy spec within a generation cycle.

    Parameters
    ----------
    spec_name:
        The ``StrategySpec.name`` this outcome describes.
    stage:
        The pipeline stage at which this outcome was decided.
    status:
        ``"passed"`` when the spec advanced past this stage successfully;
        ``"failed"`` when a hard stop was hit.
    reason:
        Human-readable explanation for failures; ``None`` on success.
    strategy_id:
        Registry UUID string, populated when ``stage == "persisted"``.
    wiki_path:
        Absolute path to the written wiki file, populated on persist.
    backtest_summary:
        JSON-safe summary dict extracted from ``BacktestResult`` on success;
        ``None`` for failed outcomes.
    """

    spec_name: str
    stage: Literal["ideation", "codegen", "validation", "sandbox", "backtest", "persisted"]
    status: Literal["passed", "failed"]
    reason: str | None
    strategy_id: str | None
    wiki_path: str | None
    backtest_summary: dict[str, Any] | None


@dataclass(frozen=True)
class CycleReport:
    """Summary of a complete (or aborted) hypothesis generation cycle.

    Parameters
    ----------
    cycle_id:
        The caller-supplied cycle identifier.
    outcomes:
        One :class:`SpecOutcome` per spec that was processed.  For an
        aborted cycle, this may be empty or contain partial results from
        specs processed before the abort.
    ideation_spend_usd:
        USD spent on the ideation call.
    codegen_spend_usd:
        Total USD spent on all codegen calls in this cycle.
    total_spend_usd:
        ``ideation_spend_usd + codegen_spend_usd``.  Asserted equal in
        tests.
    aborted:
        ``True`` when the cycle was cut short before all specs were
        processed (e.g. ``BudgetExceeded`` during ideation).
    abort_reason:
        Human-readable reason for the abort; ``None`` when
        ``aborted == False``.
    """

    cycle_id: str
    outcomes: tuple[SpecOutcome, ...]
    ideation_spend_usd: float
    codegen_spend_usd: float
    total_spend_usd: float
    aborted: bool
    abort_reason: str | None

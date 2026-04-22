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
from typing import Literal


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

"""Curated feature catalog for Layer 2 of the ideation context.

Each entry in ``FEATURES`` describes one field that is available on a market
snapshot dict passed to a generated ``compute_signal(snapshot, params)``
function.  The catalog is hand-curated (not auto-generated) so that the LLM
is told exactly what it may use.

Usage::

    from research_orchestrator.features import FEATURES, render_feature_lines
    lines = render_feature_lines()   # tuple of one-liner strings

Public API
----------
FeatureSpec
    name: str — identifier available in ``snapshot``
    expression_hint: str — how to derive the value from ``snapshot``
    one_line_doc: str — concise description for the prompt

FEATURES
    Module-level tuple of the 9 seed FeatureSpec instances.

render_feature_lines() -> tuple[str, ...]
    Format each FeatureSpec as ``"{name} — {one_line_doc} ({expression_hint})"``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSpec:
    """A single named feature available in a market snapshot.

    Parameters
    ----------
    name:
        Snake_case identifier available as ``snapshot['<name>']`` or derived.
    expression_hint:
        Short Python-like expression showing how to compute the feature from
        the raw snapshot dict (e.g. ``"snapshot['best_bid']"``).
    one_line_doc:
        One sentence describing what the feature represents.
    """

    name: str
    expression_hint: str
    one_line_doc: str


FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="best_bid",
        expression_hint="snapshot['best_bid']",
        one_line_doc="Best (highest) available back price on the order book.",
    ),
    FeatureSpec(
        name="best_ask",
        expression_hint="snapshot['best_ask']",
        one_line_doc="Best (lowest) available lay price on the order book.",
    ),
    FeatureSpec(
        name="mid",
        expression_hint="(snapshot['best_bid'] + snapshot['best_ask']) / 2",
        one_line_doc="Mid-price: arithmetic mean of best bid and best ask.",
    ),
    FeatureSpec(
        name="spread",
        expression_hint="snapshot['best_ask'] - snapshot['best_bid']",
        one_line_doc="Bid-ask spread: cost of a round-trip taker trade.",
    ),
    FeatureSpec(
        name="book_imbalance",
        expression_hint=(
            "(snapshot['best_bid_depth'] - snapshot['best_ask_depth']) / "
            "(snapshot['best_bid_depth'] + snapshot['best_ask_depth'] + 1e-9)"
        ),
        one_line_doc=(
            "Signed volume imbalance at the top of book: "
            "+1 means all depth on the bid, -1 all on the ask."
        ),
    ),
    FeatureSpec(
        name="microprice",
        expression_hint=(
            "snapshot['best_bid'] * snapshot['best_ask_depth'] / "
            "(snapshot['best_bid_depth'] + snapshot['best_ask_depth'] + 1e-9) + "
            "snapshot['best_ask'] * snapshot['best_bid_depth'] / "
            "(snapshot['best_bid_depth'] + snapshot['best_ask_depth'] + 1e-9)"
        ),
        one_line_doc=(
            "Volume-weighted mid-price that tilts toward the deeper side of "
            "the book; a short-horizon fair-value proxy."
        ),
    ),
    FeatureSpec(
        name="recent_mid_velocity",
        expression_hint=(
            "(snapshot['mid'] - params.setdefault('_prev_mid', snapshot['mid'])) / "
            "max(snapshot['elapsed_s'], 1e-3)"
        ),
        one_line_doc=(
            "Rate of change of mid-price per second over the most recent tick; "
            "positive means the mid rose, negative means it fell."
        ),
    ),
    FeatureSpec(
        name="best_bid_depth",
        expression_hint="snapshot['best_bid_depth']",
        one_line_doc="Quoted volume (GBP) available at the best back price.",
    ),
    FeatureSpec(
        name="best_ask_depth",
        expression_hint="snapshot['best_ask_depth']",
        one_line_doc="Quoted volume (GBP) available at the best lay price.",
    ),
)


def render_feature_lines() -> tuple[str, ...]:
    """Return a tuple of one-liner strings, one per feature.

    Format: ``"{name} — {one_line_doc} ({expression_hint})"``
    """
    return tuple(f"{f.name} — {f.one_line_doc} ({f.expression_hint})" for f in FEATURES)

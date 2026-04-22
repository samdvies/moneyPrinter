"""4-layer context builder for the Grok ideation prompt (Phase 6c).

Assembles an :class:`~research_orchestrator.types.IdeationContext` from four
layers:

1. **Static** — loaded from ``prompts/ideation_system.md`` (Layer 1).
2. **Features** — rendered from the curated ``features.FEATURES`` catalog
   (Layer 2).
3. **Prior cycles** — top-K and bottom-K strategies by Sharpe over the last N
   cycles from the strategy registry (Layer 3).  Empty string when fewer than 5
   prior cycles exist.
4. **Regime** — aggregate statistics over the last 7 days from the
   ``market_data_archive`` TimescaleDB hypertable (Layer 4).

Offline mode
------------
Both ``registry_repo`` and ``timescale_query`` are optional callables.  When
both are ``None`` the builder operates in offline mode: Layers 3 and 4 are
empty strings.  This keeps the unit test suite free of live Postgres
dependencies — tests inject stubs.

Async
-----
``build()`` is ``async`` because Layers 3 and 4 may need DB round-trips.  The
calling workflow (``workflow.hypothesize``) is already async.

SQL constants
-------------
``REGIME_SQL`` and ``PRIOR_CYCLES_SQL`` are module-level string constants so
they can be inspected and tested without instantiating the builder.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_orchestrator.features import render_feature_lines
from research_orchestrator.types import IdeationContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

# Query for prior-cycle data from the strategy registry.
# Returns rows of (slug, sharpe, status) ordered newest-first.
# ``sharpe`` is expected to be stored in the ``metrics`` JSONB column of
# the most recent ``strategy_runs`` row for each strategy.
PRIOR_CYCLES_SQL = """
SELECT
    s.slug,
    COALESCE((
        SELECT (sr.metrics->>'sharpe')::float
        FROM strategy_runs sr
        WHERE sr.strategy_id = s.id
          AND sr.ended_at IS NOT NULL
        ORDER BY sr.ended_at DESC
        LIMIT 1
    ), 0.0) AS sharpe,
    s.status
FROM strategies s
WHERE s.created_at >= now() - ($1 * INTERVAL '1 day')
ORDER BY s.created_at DESC
"""

# Query for regime statistics from the market_data_archive TimescaleDB
# hypertable.  Parameterised on the lookback window (in days).
# ``market_data_archive`` schema (from Phase 6a): ts, venue, market_id,
# sport, best_bid, best_ask, best_bid_depth, best_ask_depth, mid, spread.
REGIME_SQL = """
SELECT
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY spread)        AS median_spread,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY best_bid_depth) AS median_bid_depth,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY best_ask_depth) AS median_ask_depth,
    sport,
    COUNT(*) AS sport_count
FROM market_data_archive
WHERE ts >= now() - ($1 * INTERVAL '1 day')
GROUP BY sport
ORDER BY sport_count DESC
"""

# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

# Approx lookback in calendar days to use for prior-cycle queries.
_DEFAULT_PRIOR_CYCLE_LOOKBACK_DAYS: int = 30


@dataclass(frozen=True)
class ContextBuilderConfig:
    """Optional configuration overrides for :class:`ContextBuilder`.

    All fields have safe defaults.  Tests inject this to point at fixture
    directories and control K/N values.

    Parameters
    ----------
    prior_cycle_k:
        Number of top and bottom strategies to include in the prior-cycles
        summary.  Defaults to 3.
    prior_cycle_n:
        Maximum number of recent strategies to consider when computing
        top-K / bottom-K.  Defaults to 10.
    regime_lookback_days:
        How many calendar days of market data to aggregate for the regime
        statistics.  Defaults to 7.
    prior_cycle_lookback_days:
        How many calendar days back to pull strategies from the registry.
        Defaults to 30.
    prompts_dir:
        Override the directory containing the ``.md`` prompt files.  Defaults
        to ``Path(__file__).parent / "prompts"``.
    """

    prior_cycle_k: int = 3
    prior_cycle_n: int = 10
    regime_lookback_days: int = 7
    prior_cycle_lookback_days: int = _DEFAULT_PRIOR_CYCLE_LOOKBACK_DAYS
    prompts_dir: Path = field(default_factory=lambda: Path(__file__).parent / "prompts")


# ---------------------------------------------------------------------------
# Internal row types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PriorCycleEntry:
    slug: str
    sharpe: float
    status: str


@dataclass(frozen=True)
class _RegimeSportRow:
    sport: str
    count: int


@dataclass(frozen=True)
class _RegimeStats:
    median_spread: float
    median_bid_depth: float
    median_ask_depth: float
    sport_rows: tuple[_RegimeSportRow, ...]


# ---------------------------------------------------------------------------
# ContextBuilder
# ---------------------------------------------------------------------------

# Callable signatures for injected DB helpers (used in tests and offline mode).
RegistryRepoCallable = Callable[[int, int], Awaitable[list[dict[str, Any]]]]
TimescaleQueryCallable = Callable[[int], Awaitable[dict[str, Any]]]


class ContextBuilder:
    """Assemble a 4-layer :class:`IdeationContext` for the Grok ideation prompt.

    Parameters
    ----------
    registry_repo:
        Async callable ``(lookback_days, limit) -> list[dict]`` returning rows
        with keys ``slug``, ``sharpe``, ``status``.  When ``None``, Layer 3
        is always empty (offline mode).
    timescale_query:
        Async callable ``(lookback_days) -> dict`` returning a single aggregate
        row with keys ``median_spread``, ``median_bid_depth``,
        ``median_ask_depth``, ``sport_rows`` (list of ``{sport, count}``).
        When ``None``, Layer 4 is always empty (offline mode).
    config:
        Optional :class:`ContextBuilderConfig`.  Defaults are used when
        ``None``.

    Notes
    -----
    The ``db`` parameter is intentionally omitted from the public constructor
    to encourage tests to inject thin stubs (``registry_repo`` /
    ``timescale_query``) rather than a live ``algobet_common.Database``.  If
    you need live DB access, build thin wrappers around the SQL constants
    exported from this module and pass them in.
    """

    def __init__(
        self,
        *,
        registry_repo: RegistryRepoCallable | None = None,
        timescale_query: TimescaleQueryCallable | None = None,
        config: ContextBuilderConfig | None = None,
    ) -> None:
        self._registry_repo = registry_repo
        self._timescale_query = timescale_query
        self._config = config or ContextBuilderConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build(self, cycle_id: str) -> IdeationContext:
        """Assemble and return the 4-layer ideation context.

        Parameters
        ----------
        cycle_id:
            Identifier for the current generation cycle.  Currently unused in
            the assembled context but available for logging / future use.

        Returns
        -------
        IdeationContext
            All four layers as strings / tuple-of-strings matching the
            existing ``types.IdeationContext`` contract.
        """
        logger.debug("ContextBuilder.build cycle_id=%s", cycle_id)

        static = self._load_static()
        features = self._render_features()
        prior_cycles = await self._fetch_prior_cycles()
        regime = await self._fetch_regime()

        return IdeationContext(
            static=static,
            features=features,
            prior_cycles=prior_cycles,
            regime=regime,
        )

    # ------------------------------------------------------------------
    # Layer 1: static system preamble
    # ------------------------------------------------------------------

    def _load_static(self) -> str:
        """Load and return the contents of ``prompts/ideation_system.md``."""
        path = self._config.prompts_dir / "ideation_system.md"
        return path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Layer 2: feature catalog
    # ------------------------------------------------------------------

    def _render_features(self) -> tuple[str, ...]:
        """Return a tuple of one-liner strings from the curated feature catalog."""
        return render_feature_lines()

    # ------------------------------------------------------------------
    # Layer 3: prior cycles
    # ------------------------------------------------------------------

    async def _fetch_prior_cycles(self) -> str:
        """Query the strategy registry for prior-cycle performance.

        Returns an empty string when:
        - ``registry_repo`` is ``None`` (offline mode), or
        - fewer than 5 strategies are found (insufficient history).
        """
        if self._registry_repo is None:
            return ""

        cfg = self._config
        try:
            rows = await self._registry_repo(
                cfg.prior_cycle_lookback_days,
                cfg.prior_cycle_n,
            )
        except Exception:
            logger.exception("Failed to fetch prior cycles from registry")
            return ""

        entries = [
            _PriorCycleEntry(
                slug=str(r["slug"]),
                sharpe=float(r.get("sharpe") or 0.0),
                status=str(r.get("status") or "unknown"),
            )
            for r in rows
        ]

        if len(entries) < 5:
            return ""

        return self._render_prior_cycles(entries)

    def _render_prior_cycles(self, entries: list[_PriorCycleEntry]) -> str:
        """Format top-K and bottom-K entries into a multi-line string."""
        k = self._config.prior_cycle_k
        sorted_entries = sorted(entries, key=lambda e: e.sharpe, reverse=True)
        top = sorted_entries[:k]
        bottom = sorted_entries[-k:]

        lines: list[str] = []
        lines.append(f"Top {k} by Sharpe:")
        for e in top:
            lines.append(f"  - {e.slug} Sharpe={e.sharpe:.2f} state={e.status}")
        lines.append(f"Bottom {k} by Sharpe:")
        for e in bottom:
            lines.append(f"  - {e.slug} Sharpe={e.sharpe:.2f} state={e.status}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Layer 4: regime stats
    # ------------------------------------------------------------------

    async def _fetch_regime(self) -> str:
        """Query TimescaleDB for recent market regime statistics.

        Returns an empty string when:
        - ``timescale_query`` is ``None`` (offline mode), or
        - the query returns no rows.
        """
        if self._timescale_query is None:
            return ""

        cfg = self._config
        try:
            result = await self._timescale_query(cfg.regime_lookback_days)
        except Exception:
            logger.exception("Failed to fetch regime stats from Timescale")
            return ""

        if not result:
            return ""

        return self._render_regime(result)

    def _render_regime(self, result: dict[str, Any]) -> str:
        """Format regime aggregate into a short multi-line string."""
        lines: list[str] = []
        lines.append("Regime (last 7 days):")
        lines.append(f"  Median spread: {float(result.get('median_spread', 0.0)):.4f}")
        lines.append(
            f"  Median best_bid_depth: GBP {float(result.get('median_bid_depth', 0.0)):.2f}"
        )
        lines.append(
            f"  Median best_ask_depth: GBP {float(result.get('median_ask_depth', 0.0)):.2f}"
        )

        sport_rows: list[dict[str, Any]] = result.get("sport_rows", [])
        if sport_rows:
            sport_parts = ", ".join(f"{r['sport']}={r['count']}" for r in sport_rows)
            lines.append(f"  Sport mix: {sport_parts}")

        return "\n".join(lines)

"""SQLite-backed daily USD spend tracker for xAI API calls.

Phase 6c budget guard — every call to the xAI API is recorded here so that
:class:`LLMClient` can check ``would_exceed`` *before* making any HTTP
round-trip.

Precision note
--------------
Costs are stored and returned as Python ``float``.  The aggregation precision
requirement is $0.01 (the cap is expressed in dollars, not sub-cent).
``float`` gives ~15 decimal digits of precision on IEEE 754 hardware, which
is more than sufficient.  ``Decimal`` would be overkill and would complicate
the SQLite ``REAL`` storage round-trip.

Day boundary
------------
"Today" is the UTC calendar day of ``now()``.  Queries use
``ts_utc >= today_start AND ts_utc < tomorrow_start`` as ISO 8601 strings,
which sorts correctly because the format is zero-padded and
lexicographically ordered.

DB path
-------
Default: ``var/research_orchestrator/spend.db`` relative to the repo root.
The parent directory is created automatically on first use.  For tests,
pass an explicit ``db_path`` to a ``tmp_path`` location.

Pricing table
-------------
Module-level constant ``MODEL_PRICING`` maps model id → :class:`ModelPricing`.
Values are **unverified placeholders** (see comment below).  Task 4's live
integration test will catch any drift against the real xAI pricing page.

Clock injection
---------------
``SpendTracker.__init__`` accepts an optional ``now: Callable[[], datetime]``
parameter.  The default is ``lambda: datetime.now(timezone.utc)``.  Tests
pass a frozen/advancing callable to control day-boundary behaviour without
monkey-patching.

Windows compatibility
---------------------
All path operations use :class:`pathlib.Path`.  No POSIX-specific
assumptions are made.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Default DB path (relative to repo root at import time; callers may override)
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = Path(__file__).parents[5] / "var" / "research_orchestrator" / "spend.db"

# ---------------------------------------------------------------------------
# Pricing constants
# ---------------------------------------------------------------------------
# IMPORTANT: These values are UNVERIFIED PLACEHOLDERS as of 2026-04-22.
# The xAI pricing page (https://x.ai/api) could not be accessed during
# implementation.  Task 4's live-key integration test will catch any drift.
# When updating, replace the values AND change the comment date below.
#
# pricing: UNVERIFIED PLACEHOLDERS — update from https://x.ai/api
# (placeholder as of 2026-04-22; verify and mark # verified YYYY-MM-DD)
#
# Placeholder values (per 1M tokens):
#   grok-4:                   input $5.00 / output $15.00
#   grok-4-fast-reasoning:    input $0.20 / output $0.50
#   grok-4-fast-non-reasoning: input $0.20 / output $0.50


@dataclass(frozen=True)
class ModelPricing:
    """Per-million-token USD prices for a single model.

    ``input_per_million``  — cost in USD per 1 000 000 input tokens.
    ``output_per_million`` — cost in USD per 1 000 000 output tokens.
    """

    input_per_million: float
    output_per_million: float


MODEL_PRICING: dict[str, ModelPricing] = {
    # UNVERIFIED PLACEHOLDERS — see module docstring
    "grok-4": ModelPricing(input_per_million=5.00, output_per_million=15.00),
    "grok-4-fast-reasoning": ModelPricing(input_per_million=0.20, output_per_million=0.50),
    "grok-4-fast-non-reasoning": ModelPricing(input_per_million=0.20, output_per_million=0.50),
}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UnknownModelError(KeyError):
    """Raised when ``record()`` is called with a model id not in MODEL_PRICING."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(model)

    def __str__(self) -> str:
        return (
            f"Model '{self.model}' is not in MODEL_PRICING. "
            f"Known models: {sorted(MODEL_PRICING)}"
        )


# ---------------------------------------------------------------------------
# Schema DDL (applied once on first connection)
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS spend_events (
    ts_utc TEXT NOT NULL,
    model  TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    usd  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spend_events_ts ON spend_events(ts_utc);
"""

# ---------------------------------------------------------------------------
# SpendTracker
# ---------------------------------------------------------------------------


class SpendTracker:
    """SQLite-backed daily USD spend tracker.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  The parent directory is created
        automatically.  Defaults to ``var/research_orchestrator/spend.db``
        relative to the repository root.
    now:
        Callable returning the current UTC datetime.  Defaults to
        ``lambda: datetime.now(UTC)``.  Inject a stub in tests to
        control the UTC day boundary deterministically.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._db_path: Path = db_path if db_path is not None else _DEFAULT_DB_PATH
        self._now: Callable[[], datetime] = now if now is not None else (lambda: datetime.now(UTC))
        self._ensure_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Record a single API call and return the USD cost.

        Parameters
        ----------
        model:
            xAI model id (must be a key in :data:`MODEL_PRICING`).
        input_tokens:
            Number of input tokens consumed.
        output_tokens:
            Number of output tokens generated.

        Returns
        -------
        float
            The USD cost of this single call.

        Raises
        ------
        UnknownModelError
            If ``model`` is not present in :data:`MODEL_PRICING`.
        """
        if model not in MODEL_PRICING:
            raise UnknownModelError(model)

        pricing = MODEL_PRICING[model]
        usd = (
            input_tokens * pricing.input_per_million + output_tokens * pricing.output_per_million
        ) / 1_000_000

        ts_utc = self._now().isoformat()
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "INSERT INTO spend_events (ts_utc, model, input_tokens, output_tokens, usd) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts_utc, model, input_tokens, output_tokens, usd),
            )
        return usd

    def cumulative_today_usd(self) -> float:
        """Return the total USD spent today (UTC calendar day of ``now()``)."""
        today_start, tomorrow_start = self._today_bounds()
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(usd), 0.0) FROM spend_events "
                "WHERE ts_utc >= ? AND ts_utc < ?",
                (today_start, tomorrow_start),
            ).fetchone()
        return float(row[0])

    def would_exceed(self, estimated_usd: float, cap_usd: float) -> bool:
        """Return True if cumulative spend + estimate would strictly exceed the cap.

        Parameters
        ----------
        estimated_usd:
            Estimated cost of the *next* call (before it is made).
        cap_usd:
            Daily budget cap in USD.
        """
        return (self.cumulative_today_usd() + estimated_usd) > cap_usd

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_db(self) -> None:
        """Create parent directory and initialise the schema if needed."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript(_DDL)

    def _today_bounds(self) -> tuple[str, str]:
        """Return (today_start_iso, tomorrow_start_iso) for the current UTC day."""
        now = self._now()
        # Normalise to UTC if the callable returns a tz-aware datetime
        if now.tzinfo is not None:
            now = now.astimezone(UTC)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)
        tomorrow = today + timedelta(days=1)
        return today.isoformat(), tomorrow.isoformat()

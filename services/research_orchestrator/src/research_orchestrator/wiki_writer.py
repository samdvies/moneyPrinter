"""Write backtest results back into a strategy's wiki file.

Phase 6b.5 responsibility: after ``workflow.run_backtest`` seals a
``strategy_runs`` row, the orchestrator rewrites the corresponding
``wiki/30-Strategies/<slug>.md`` so the Obsidian vault is a faithful
mirror of the registry for human review.

Two edits are performed, both in-place and idempotent:

1. Frontmatter: replace the ``updated: YYYY-MM-DD`` line with today's
   date (derived from the supplied ``run_ended_at``). Key order and the
   rest of the frontmatter (including quoting style) are preserved by
   using a literal line-level substitution rather than a YAML
   round-trip.

2. Body: locate the ``## Backtest Results`` heading and replace all
   lines between it and the next ``## `` heading with a freshly
   formatted bullet list derived from ``run_metrics``.

Disk I/O is intentionally kept out of ``workflow.run_backtest``; the
workflow stays DB-only and the orchestrator (``runner.run_once``) is
the sole caller of this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .errors import OrchestratorError

_BACKTEST_HEADING = "## Backtest Results"
_FRONTMATTER_FENCE = "---"


def _format_decimal(value: Any) -> str:
    """Format a monetary value as a plain string.

    ``run_metrics`` values may arrive as ``Decimal`` (harness canonical
    type) or as ``str`` (post-JSON round-trip via ``strategy_runs``).
    Both render identically.
    """
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _format_float(value: Any) -> str:
    return f"{float(value):.4f}"


def _format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _render_backtest_block(run_metrics: Mapping[str, Any]) -> list[str]:
    """Render the bullet list that sits under ``## Backtest Results``.

    Returned lines do NOT include the heading itself and do NOT include
    a trailing blank line — the caller stitches those in so the overall
    file shape (blank line before the next heading) is preserved.
    """
    period = (
        f"{_format_datetime(run_metrics['started_at'])}"
        f" -> {_format_datetime(run_metrics['ended_at'])}"
    )
    return [
        f"- Period: {period}",
        f"- Trades: {int(run_metrics['n_trades'])}",
        f"- Win rate: {_format_float(run_metrics['win_rate'])}",
        f"- Sharpe: {_format_float(run_metrics['sharpe'])}",
        f"- Total P&L: {_format_decimal(run_metrics['total_pnl_gbp'])}",
        f"- Max drawdown: {_format_decimal(run_metrics['max_drawdown_gbp'])}",
        f"- Ticks: {int(run_metrics['n_ticks_consumed'])}",
    ]


def _rewrite_updated_field(lines: list[str], new_date: str) -> list[str]:
    """Replace the ``updated: ...`` line inside the leading frontmatter.

    Only the first ``updated:`` line between the two ``---`` fences is
    touched; a stray ``updated:`` appearing later in the body (unlikely
    but possible in prose) is not rewritten.
    """
    if not lines or lines[0].strip() != _FRONTMATTER_FENCE:
        raise OrchestratorError("wiki file must start with a '---' frontmatter fence")
    # Locate closing fence.
    close_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_FENCE:
            close_idx = idx
            break
    if close_idx is None:
        raise OrchestratorError("wiki file is missing the closing '---' frontmatter fence")

    for idx in range(1, close_idx):
        stripped = lines[idx].lstrip()
        if stripped.startswith("updated:"):
            lines[idx] = f"updated: {new_date}"
            return lines

    raise OrchestratorError("frontmatter missing required 'updated:' field")


def _rewrite_backtest_block(lines: list[str], run_metrics: Mapping[str, Any]) -> list[str]:
    """Replace the body block under ``## Backtest Results`` in-place.

    The block runs from the line *after* the heading up to (but not
    including) the next ``## `` heading. A single trailing blank line is
    preserved so the next heading stays separated by exactly one blank
    line — matching the file's existing convention.
    """
    heading_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.strip() == _BACKTEST_HEADING:
            heading_idx = idx
            break
    if heading_idx is None:
        raise OrchestratorError(f"wiki file missing '{_BACKTEST_HEADING}' heading")

    # Find the next section heading after the Backtest Results heading.
    next_heading_idx: int | None = None
    for idx in range(heading_idx + 1, len(lines)):
        if lines[idx].startswith("## "):
            next_heading_idx = idx
            break

    block_lines = _render_backtest_block(run_metrics)
    # Insert a blank line before the next heading (if any) to match the
    # file's existing convention of one blank line between sections.
    if next_heading_idx is not None:
        new_lines = lines[: heading_idx + 1] + block_lines + [""] + lines[next_heading_idx:]
    else:
        new_lines = lines[: heading_idx + 1] + block_lines
    return new_lines


def write_backtest_results(
    wiki_path: Path,
    run_metrics: Mapping[str, Any],
    run_ended_at: datetime,
) -> None:
    """Rewrite ``wiki_path`` with the latest backtest metrics.

    - ``run_metrics`` must contain ``started_at``, ``ended_at``,
      ``n_trades``, ``win_rate``, ``sharpe``, ``total_pnl_gbp``,
      ``max_drawdown_gbp``, ``n_ticks_consumed`` (the fixed shape emitted
      by ``backtest_engine.harness``).
    - ``run_ended_at`` drives the frontmatter ``updated:`` field
      (formatted ``YYYY-MM-DD``). This is the authoritative wall-clock
      moment at which the orchestrator finished the run and wrote back —
      the caller passes ``datetime.now(UTC)``, not the harness clock.

    Preserves frontmatter key order, all body sections other than
    ``## Backtest Results``, and file-level line endings (LF).
    """
    text = wiki_path.read_text(encoding="utf-8")
    # splitlines() strips the trailing newline; track whether the
    # original file ended with one so we can restore it exactly.
    had_trailing_newline = text.endswith("\n")
    lines = text.splitlines()

    new_date = run_ended_at.strftime("%Y-%m-%d")
    lines = _rewrite_updated_field(lines, new_date)
    lines = _rewrite_backtest_block(lines, run_metrics)

    output = "\n".join(lines)
    if had_trailing_newline:
        output += "\n"
    wiki_path.write_text(output, encoding="utf-8")

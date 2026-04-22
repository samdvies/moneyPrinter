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

Phase 6c additions
------------------
``write_hypothesis`` — write a brand-new proposed-strategy wiki file to
``wiki/30-Strategies/proposed/<name>.md`` with YAML frontmatter that
satisfies both the 6b loader contract and the 6c provenance fields.

``append_daily_log_section`` — append a Hypothesis Cycle summary block
to ``wiki/70-Daily/YYYY-MM-DD.md``, creating the file if absent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import OrchestratorError

if TYPE_CHECKING:
    from .types import SpecOutcome, StrategySpec

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
    ``## Backtest Results``, and the file's dominant line ending (LF or
    CRLF). Detecting CRLF matters on Windows-authored wiki files — a naive
    rejoin with ``"\n"`` would silently normalise the whole file to LF
    and produce a spurious git diff on first write.
    """
    # Read with newline="" to disable universal-newline translation so
    # we can faithfully detect the file's dominant line ending; otherwise
    # Python would transparently convert CRLF -> LF on read and we'd lose
    # the information needed to round-trip Windows-authored files.
    with wiki_path.open(encoding="utf-8", newline="") as fh:
        text = fh.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    # splitlines() strips the trailing newline and handles both CRLF and
    # LF transparently; track whether the original file ended with a
    # newline so we can restore the trailing terminator exactly.
    had_trailing_newline = text.endswith(("\r\n", "\n"))
    lines = text.splitlines()

    new_date = run_ended_at.strftime("%Y-%m-%d")
    lines = _rewrite_updated_field(lines, new_date)
    lines = _rewrite_backtest_block(lines, run_metrics)

    output = newline.join(lines)
    if had_trailing_newline:
        output += newline
    wiki_path.write_text(output, encoding="utf-8", newline="")


# ---------------------------------------------------------------------------
# Phase 6c: write_hypothesis
# ---------------------------------------------------------------------------


def write_hypothesis(
    wiki_root: Path,
    spec: StrategySpec,
    source: str,
    backtest_result: Mapping[str, Any],
    cycle_id: str,
    spec_sha256: str,
    code_sha256: str,
) -> Path:
    """Write a proposed-strategy wiki file to ``wiki_root/30-Strategies/proposed/<name>.md``.

    The file is always written with LF line endings (``\\n``).  This is
    intentional for newly-created files — the round-trip CRLF concern only
    applies to rewrites of *existing* Windows-authored files (handled in
    ``write_backtest_results``).  New files written by this function can safely
    default to LF; Obsidian on Windows opens them without issue.

    The frontmatter satisfies the 6b wiki_loader contract
    (``title``, ``strategy-id``, ``venue``, ``module``, ``parameters``) plus
    the 6c provenance fields (``generated_by``, ``cycle_id``, ``spec_sha256``,
    ``code_sha256``).

    Parameters
    ----------
    wiki_root:
        Root of the Obsidian vault (the ``wiki/`` directory).
    spec:
        The ``StrategySpec`` produced by the LLM ideation stage.
    source:
        The validated, sandbox-checked Python source for ``compute_signal``.
    backtest_result:
        Metrics dict from ``BacktestResult``.  Must contain at least the keys
        required by ``_render_backtest_block``.
    cycle_id:
        Hypothesis cycle identifier string.
    spec_sha256:
        Hex SHA-256 of the spec serialised as JSON (sorted keys).
    code_sha256:
        Hex SHA-256 of the ``source`` string.

    Returns
    -------
    Path
        Absolute path of the written file.
    """
    today = date.today().isoformat()

    # Build a parameters YAML block as nested key-value pairs.
    # ``strategy_registry.wiki_loader`` requires ``parameters`` to be a
    # YAML mapping; we represent each ParamRange as a plain dict.
    params_yaml_lines: list[str] = []
    for pname, pranges in spec.params.items():
        params_yaml_lines.append(f"  {pname}: {pranges.default}")

    params_block = "\n".join(params_yaml_lines) if params_yaml_lines else "  {}"

    # The loader requires ``module`` to start with ``backtest_engine.strategies.``.
    module_path = f"backtest_engine.strategies.{spec.name}"

    # Tags list
    tags_str = f"[strategy, hypothesis, generated, {cycle_id}]"

    frontmatter_lines = [
        "---",
        f'title: "{spec.name}"',
        "type: strategy",
        f"strategy-id: {spec.name}",
        "venue: betfair",
        "status: hypothesis",
        "author-agent: orchestrator-6c",
        f"created: {today}",
        f"updated: {today}",
        f"module: {module_path}",
        f"tags: {tags_str}",
        "parameters:",
        params_block,
        "generated_by: orchestrator-6c",
        f"cycle_id: {cycle_id}",
        f"spec_sha256: {spec_sha256}",
        f"code_sha256: {code_sha256}",
        "---",
    ]

    # Parameter section (human-readable)
    param_section_lines = ["## Parameters"]
    for pname, pranges in spec.params.items():
        param_section_lines.append(
            f"- {pname}: kind={pranges.kind} low={pranges.low} high={pranges.high}"
            f" default={pranges.default}"
        )

    # Backtest block
    backtest_section_lines: list[str] = []
    if backtest_result:
        backtest_section_lines = ["## Backtest Results", *_render_backtest_block(backtest_result)]

    body_parts: list[str] = [
        "\n".join(frontmatter_lines),
        "",
        f"## Rationale\n{spec.rationale}",
        "",
        f"## Signal Formula\n{spec.signal_formula}",
        "",
        "\n".join(param_section_lines),
        "",
        f"## Entry Rules\n{spec.entry_rules}",
        "",
        f"## Exit Rules\n{spec.exit_rules}",
        "",
        f"## Expected Edge\n{spec.expected_edge}",
    ]

    if backtest_section_lines:
        body_parts.extend(["", "\n".join(backtest_section_lines)])

    body_parts.extend(
        [
            "",
            "## Generated Code",
            "```python",
            source,
            "```",
            "",
        ]
    )

    content = "\n".join(body_parts)

    dest_dir = wiki_root / "30-Strategies" / "proposed"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{spec.name}.md"
    dest_path.write_text(content, encoding="utf-8", newline="")
    return dest_path


# ---------------------------------------------------------------------------
# Phase 6c: append_daily_log_section
# ---------------------------------------------------------------------------


def append_daily_log_section(
    wiki_root: Path,
    cycle_id: str,
    outcomes: Sequence[SpecOutcome],
    total_spend_usd: float,
    today: date | None = None,
) -> Path:
    """Append a Hypothesis Cycle section to the daily log.

    Creates ``wiki_root/70-Daily/YYYY-MM-DD.md`` with minimal frontmatter if
    the file does not yet exist, then appends a ``## Hypothesis Cycle``
    section.  On subsequent calls for the same date the section is appended
    (not overwritten), so two cycles on the same day produce two sections.

    Always writes with LF line endings (same rationale as ``write_hypothesis``).

    Parameters
    ----------
    wiki_root:
        Root of the Obsidian vault.
    cycle_id:
        Hypothesis cycle identifier string.
    outcomes:
        Sequence of ``SpecOutcome`` produced by the cycle.
    total_spend_usd:
        Total USD spend for the cycle (ideation + codegen).
    today:
        Date to use for the log file name.  Defaults to ``date.today()``.

    Returns
    -------
    Path
        Absolute path of the daily log file.
    """
    log_date = today if today is not None else date.today()
    date_str = log_date.isoformat()

    log_dir = wiki_root / "70-Daily"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{date_str}.md"

    if not log_path.exists():
        frontmatter = "\n".join(
            [
                "---",
                f"title: {date_str}",
                "type: daily",
                "tags: [daily, hypothesis-cycle]",
                f"updated: {date_str}",
                "status: active",
                "---",
                "",
            ]
        )
        log_path.write_text(frontmatter, encoding="utf-8", newline="")

    # Build the section to append
    per_spec_lines: list[str] = []
    proposed_links: list[str] = []
    for outcome in outcomes:
        reason_part = outcome.reason if outcome.reason else "ok"
        per_spec_lines.append(
            f"  - {outcome.spec_name}: {outcome.stage}/{outcome.status} — {reason_part}"
        )
        if outcome.status == "passed" and outcome.wiki_path is not None:
            # Obsidian wiki links use forward-slash paths
            proposed_links.append(f"  - [[30-Strategies/proposed/{outcome.spec_name}]]")

    section_lines: list[str] = [
        f"## Hypothesis Cycle {cycle_id}",
        f"- Total spend: ${total_spend_usd:.2f} USD",
        "- Per-spec outcomes:",
    ]
    section_lines.extend(per_spec_lines)

    if proposed_links:
        section_lines.append("- Proposed strategy files:")
        section_lines.extend(proposed_links)

    section = "\n".join(section_lines) + "\n"

    # Append — open in append mode so concurrent cycles on the same date
    # add separate sections without clobbering each other.
    with log_path.open("a", encoding="utf-8", newline="") as fh:
        fh.write("\n" + section)

    return log_path

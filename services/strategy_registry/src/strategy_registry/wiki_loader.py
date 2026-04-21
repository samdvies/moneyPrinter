"""Load a strategy from a ``wiki/30-Strategies/<slug>.md`` file into the registry.

Contract (authoritative — 6c code generation depends on this shape):

    async def load_strategy_from_wiki(wiki_path: Path, db: Database) -> Strategy

Steps:
    1. Read the file, split the leading ``---``-fenced YAML frontmatter block.
    2. Parse the frontmatter with PyYAML (``safe_load``).
    3. Validate required keys: ``title``, ``strategy-id``, ``venue``, ``module``,
       ``parameters``.
    4. Enforce the filename invariant: ``wiki_path.stem == frontmatter["strategy-id"]``.
       The filename is the canonical key; a mismatch is a human/tooling bug that
       must fail loud.
    5. Enforce the module namespace allowlist: ``frontmatter["module"]`` must start
       with ``backtest_engine.strategies.`` (defense in depth — 6c's AST check is
       belt-and-braces). Any other dotted path is rejected *before* ``import_module``
       is called, closing the attack surface for LLM-emitted module paths in 6c.
    6. ``importlib.import_module(frontmatter["module"])`` — verifies the dotted
       path resolves. Missing module raises ``ModuleNotFoundError`` unchanged
       so callers can distinguish that from a shape failure.
    7. Verify the imported module has a callable ``on_tick`` attribute. Do NOT
       invoke it here — AST / runtime safety is 6c's concern.
    8. ``upsert_strategy(slug=stem, parameters=frontmatter["parameters"],
       wiki_path=str(wiki_path))`` — idempotent under re-load.

Status is never written by the loader (it defaults to ``hypothesis`` on insert
and is preserved on update). The lifecycle state machine is the sole writer of
``strategies.status``.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml
from algobet_common.db import Database

from .crud import upsert_strategy
from .errors import StrategyLoadError
from .models import Strategy

_REQUIRED_KEYS: tuple[str, ...] = (
    "title",
    "strategy-id",
    "venue",
    "module",
    "parameters",
)

_FRONTMATTER_FENCE = "---"

# Allowlist prefix for strategy module paths.  Only modules under this
# namespace may be imported by the loader.  6c can extend this constant if
# additional namespaces are needed — keep it narrow until then.
_ALLOWED_MODULE_PREFIX = "backtest_engine.strategies."


def _split_frontmatter(text: str) -> str:
    """Return the YAML block between the two leading ``---`` fences.

    Raises ``StrategyLoadError`` if the file does not start with ``---`` or the
    closing fence is missing. Body content after the closing fence is
    discarded — the loader only cares about frontmatter.
    """
    # Normalise line endings so Windows-authored files parse identically.
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_FENCE:
        raise StrategyLoadError("wiki file must start with a '---' frontmatter fence")
    # Find the closing fence.
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_FENCE:
            return "\n".join(lines[1:idx])
    raise StrategyLoadError("wiki file is missing the closing '---' frontmatter fence")


def _parse_frontmatter(raw: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise StrategyLoadError(f"invalid YAML in frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise StrategyLoadError(f"frontmatter must be a YAML mapping, got {type(data).__name__}")
    return data


def _validate_keys(frontmatter: dict[str, Any]) -> None:
    missing = [key for key in _REQUIRED_KEYS if key not in frontmatter]
    if missing:
        raise StrategyLoadError(f"frontmatter missing required keys: {sorted(missing)}")
    if not isinstance(frontmatter["parameters"], dict):
        raise StrategyLoadError("frontmatter 'parameters' must be a YAML mapping")


def _verify_module_shape(dotted_path: str) -> None:
    """Import ``dotted_path`` and verify it exposes a callable ``on_tick``.

    ``dotted_path`` must begin with ``backtest_engine.strategies.`` (see
    ``_ALLOWED_MODULE_PREFIX``).  This check runs *before* ``import_module``
    so that side-effectful imports outside the allowed namespace are blocked
    entirely.  defense in depth — 6c's AST check is belt-and-braces.

    A missing module raises ``ModuleNotFoundError`` unchanged (per plan).
    A module that imports but has no callable ``on_tick`` attribute raises
    ``StrategyLoadError`` — this is the structural ``StrategyModule`` check.
    The function itself is never invoked; runtime safety is 6c's job.
    """
    if not dotted_path.startswith(_ALLOWED_MODULE_PREFIX):
        raise StrategyLoadError(
            f"module '{dotted_path}' outside allowed namespace '{_ALLOWED_MODULE_PREFIX}*'"
        )
    module = importlib.import_module(dotted_path)
    attr = getattr(module, "on_tick", None)
    if attr is None:
        raise StrategyLoadError(f"module '{dotted_path}' does not expose an 'on_tick' attribute")
    if not callable(attr):
        raise StrategyLoadError(
            f"module '{dotted_path}'.on_tick is not callable (got {type(attr).__name__})"
        )


async def load_strategy_from_wiki(wiki_path: Path, db: Database) -> Strategy:
    """Parse ``wiki_path``, verify the module shape, and UPSERT the registry row.

    The slug is taken from ``wiki_path.stem`` and must match
    ``frontmatter['strategy-id']``. Returns the resulting ``Strategy`` row
    (freshly inserted at ``status='hypothesis'`` on first load; otherwise the
    existing row with updated ``parameters`` and ``wiki_path``).
    """
    text = wiki_path.read_text(encoding="utf-8")
    frontmatter = _parse_frontmatter(_split_frontmatter(text))
    _validate_keys(frontmatter)

    slug = wiki_path.stem
    declared_id = frontmatter["strategy-id"]
    if declared_id != slug:
        raise StrategyLoadError(
            f"filename stem '{slug}' does not match frontmatter strategy-id '{declared_id}'"
        )

    dotted_path = frontmatter["module"]
    if not isinstance(dotted_path, str) or not dotted_path:
        raise StrategyLoadError("frontmatter 'module' must be a non-empty dotted-path string")

    # ModuleNotFoundError intentionally propagates unwrapped.
    _verify_module_shape(dotted_path)

    parameters: dict[str, Any] = dict(frontmatter["parameters"])
    return await upsert_strategy(
        db,
        slug=slug,
        parameters=parameters,
        wiki_path=str(wiki_path),
    )

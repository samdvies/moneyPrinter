"""Tests for ``strategy_registry.wiki_loader.load_strategy_from_wiki``.

Unit tests (no DB) cover every pre-UPSERT failure mode: mismatched filename,
missing key, missing module, module-without-on_tick. The integration test
exercises the UPSERT semantics end-to-end against the local Postgres.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from algobet_common.db import Database
from strategy_registry.errors import StrategyLoadError
from strategy_registry.models import Status, Strategy
from strategy_registry.wiki_loader import load_strategy_from_wiki

_FIXTURES = Path(__file__).parent / "fixtures" / "wiki"


# ---------------------------------------------------------------------------
# Happy path (unit: patches upsert_strategy, no DB required)
# ---------------------------------------------------------------------------


async def test_happy_path_parses_and_upserts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_upsert(
        db: Any,
        *,
        slug: str,
        parameters: dict[str, Any],
        wiki_path: str,
    ) -> Strategy:
        captured["slug"] = slug
        captured["parameters"] = parameters
        captured["wiki_path"] = wiki_path
        from datetime import UTC, datetime

        return Strategy(
            id=uuid.uuid4(),
            slug=slug,
            status=Status.HYPOTHESIS,
            parameters=parameters,
            wiki_path=wiki_path,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    monkeypatch.setattr(
        "strategy_registry.wiki_loader.upsert_strategy",
        fake_upsert,
    )

    result = await load_strategy_from_wiki(
        _FIXTURES / "happy-trivial.md",
        AsyncMock(),
    )

    assert result.slug == "happy-trivial"
    assert result.status == Status.HYPOTHESIS
    assert captured["slug"] == "happy-trivial"
    assert captured["parameters"] == {"stake_gbp": "10", "venue": "betfair"}
    assert captured["wiki_path"].endswith("happy-trivial.md")


# ---------------------------------------------------------------------------
# Failure: filename stem != frontmatter strategy-id
# ---------------------------------------------------------------------------


async def test_filename_strategy_id_mismatch_raises() -> None:
    stub = AsyncMock()
    with pytest.raises(StrategyLoadError, match="does not match frontmatter"):
        await load_strategy_from_wiki(_FIXTURES / "mismatched-id.md", stub)
    stub.assert_not_called()


# ---------------------------------------------------------------------------
# Failure: missing required frontmatter key
# ---------------------------------------------------------------------------


async def test_missing_required_key_raises() -> None:
    with pytest.raises(StrategyLoadError, match="missing required keys"):
        await load_strategy_from_wiki(
            _FIXTURES / "missing-key.md",
            AsyncMock(),
        )


# ---------------------------------------------------------------------------
# Failure: module dotted path does not resolve
# ---------------------------------------------------------------------------


async def test_missing_module_raises_module_not_found() -> None:
    # The plan explicitly says ModuleNotFoundError propagates unwrapped.
    with pytest.raises(ModuleNotFoundError):
        await load_strategy_from_wiki(
            _FIXTURES / "missing-module.md",
            AsyncMock(),
        )


# ---------------------------------------------------------------------------
# Failure: module imports but has no on_tick attr
# ---------------------------------------------------------------------------


async def test_module_without_on_tick_raises_strategy_load_error() -> None:
    with pytest.raises(StrategyLoadError, match="on_tick"):
        await load_strategy_from_wiki(
            _FIXTURES / "missing-on-tick.md",
            AsyncMock(),
        )


# ---------------------------------------------------------------------------
# Failure: module path outside allowed namespace (``backtest_engine.strategies.*``)
# ---------------------------------------------------------------------------


async def test_module_outside_allowed_namespace_raises() -> None:
    """Allowlist check must fire *before* import_module.

    ``os.path`` is a real, importable stdlib module — using it here verifies
    that the guard blocks the import entirely rather than letting it run and
    checking afterwards.  The error message must name the disallowed namespace.
    """
    with pytest.raises(StrategyLoadError, match="outside allowed namespace") as exc_info:
        await load_strategy_from_wiki(
            _FIXTURES / "outside-namespace.md",
            AsyncMock(),
        )
    assert "backtest_engine.strategies." in str(exc_info.value)


# ---------------------------------------------------------------------------
# Failure: wiki file with no frontmatter fence at all
# ---------------------------------------------------------------------------


async def test_no_frontmatter_fence_raises(tmp_path: Path) -> None:
    bad = tmp_path / "no-fence.md"
    bad.write_text("Just some markdown, no frontmatter.\n", encoding="utf-8")
    with pytest.raises(StrategyLoadError, match="frontmatter fence"):
        await load_strategy_from_wiki(bad, AsyncMock())


async def test_unclosed_frontmatter_raises(tmp_path: Path) -> None:
    bad = tmp_path / "unclosed.md"
    bad.write_text("---\ntitle: x\nstrategy-id: unclosed\n", encoding="utf-8")
    with pytest.raises(StrategyLoadError, match="closing '---'"):
        await load_strategy_from_wiki(bad, AsyncMock())


# ---------------------------------------------------------------------------
# Integration: UPSERT round-trip — requires Postgres
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(postgres_dsn: str, require_postgres: None) -> AsyncGenerator[Database, None]:
    database = Database(postgres_dsn)
    await database.connect()
    yield database
    await database.close()


@pytest.mark.integration
async def test_upsert_preserves_id_and_status_on_reload(db: Database, tmp_path: Path) -> None:
    """Two consecutive loads of the same slug keep the UUID + status, update params."""
    # Copy the fixture into tmp_path with a unique slug so parallel runs don't collide.
    slug = f"upsert-rt-{uuid.uuid4().hex[:8]}"
    dest = tmp_path / f"{slug}.md"
    src = _FIXTURES / "upsert-roundtrip.md"
    shutil.copyfile(src, dest)

    # Rewrite the strategy-id line inside the copy to match the fresh slug.
    original = dest.read_text(encoding="utf-8")
    rewritten = original.replace("strategy-id: upsert-roundtrip", f"strategy-id: {slug}")
    dest.write_text(rewritten, encoding="utf-8")

    first = await load_strategy_from_wiki(dest, db)
    assert first.slug == slug
    assert first.status == Status.HYPOTHESIS
    assert first.parameters == {"stake_gbp": "10", "venue": "betfair"}

    # Simulate the operator advancing the strategy out of 'hypothesis' between
    # loads; the loader must not revert it.
    from strategy_registry.crud import transition

    await transition(db, first.id, Status.BACKTESTING)

    # Mutate parameters on disk, reload — same UUID, new parameters, status preserved.
    mutated = dest.read_text(encoding="utf-8").replace('stake_gbp: "10"', 'stake_gbp: "25"')
    dest.write_text(mutated, encoding="utf-8")

    second = await load_strategy_from_wiki(dest, db)
    assert second.id == first.id, "UPSERT must reuse the existing row"
    assert second.status == Status.BACKTESTING, "loader must not clobber status"
    assert second.parameters["stake_gbp"] == "25"
    assert second.wiki_path == str(dest)


# ---------------------------------------------------------------------------
# Integration: the real repo wiki file round-trips through the loader
# ---------------------------------------------------------------------------
#
# The fixtures above exercise the parser against controlled inputs. This test
# exercises the on-disk contract between ``wiki/30-Strategies/<slug>.md`` and
# the registry — if a Phase 6b.3 edit to the real file breaks the frontmatter
# contract (missing key, wrong module path, filename mismatch), CI catches it
# here rather than only at operator runtime via ``scripts.seed_reference_strategy``.


def _repo_root() -> Path:
    # services/strategy_registry/tests/test_wiki_loader.py -> repo root is 4 parents up.
    return Path(__file__).resolve().parents[3]


@pytest.mark.integration
async def test_repo_wiki_reference_file_loads(db: Database) -> None:
    """The real ``mean-reversion-ref.md`` file in the repo loads into the registry."""
    wiki_path = _repo_root() / "wiki" / "30-Strategies" / "mean-reversion-ref.md"
    assert wiki_path.exists(), f"reference wiki file missing: {wiki_path}"

    # Clean any pre-existing row so the `status == HYPOTHESIS` assertion below is
    # deterministic. The loader's UPSERT preserves status on re-entry, so an
    # earlier test run or a manual `python -m scripts.seed_reference_strategy`
    # followed by a transition would otherwise leave the row at BACKTESTING/etc.
    async with db.acquire() as conn:
        await conn.execute(
            "DELETE FROM strategies WHERE slug = $1",
            "mean-reversion-ref",
        )

    strategy = await load_strategy_from_wiki(wiki_path, db)

    assert strategy.slug == "mean-reversion-ref"
    assert strategy.status == Status.HYPOTHESIS
    assert strategy.wiki_path == str(wiki_path)
    assert strategy.parameters == {
        "window_size": 30,
        "z_threshold": 1.5,
        "stake_gbp": "10",
        "venue": "betfair",
    }

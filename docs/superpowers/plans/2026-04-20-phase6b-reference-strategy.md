# Plan: Phase 6b — Reference Strategy + Wiki↔Registry Wiring

> **Roadmap parent:** `docs/superpowers/plans/2026-04-20-phase6-7-roadmap.md`
> **Preceded by:** `docs/superpowers/plans/2026-04-20-phase6a-backtest-harness.md` (merged into `phase6-edge-generation`)
> **Branch:** `phase6-edge-generation` (same branch; commits layered on top of 6a)

## Why now

6a shipped a real harness wired into the orchestrator, but the orchestrator still runs `backtest_engine.strategies.trivial` (best-ask ≤ 1.50 → BACK) against a 10-tick `SyntheticSource` of best-ask 1.40. Every run rubber-stamps advancement to `paper` because the strategy is a tautology. There is no honest evaluation pipeline and nothing in `wiki/30-Strategies/` — so when 6c starts generating strategy specs, there is no template, no loader, no ground-truth reference to compare them to.

6b closes both gaps with one hand-written strategy:

1. **A reference strategy with a real — but simple — inefficiency claim** runs through the 6a harness and produces non-zero metrics on realistic synthetic ticks (not a rigged source).
2. **A wiki↔registry loader** turns a `wiki/30-Strategies/<slug>.md` file into a registry row plus an importable Python module, so the orchestrator can pick up research-generated strategies from disk in 6c without further plumbing.

This phase is the **ground truth** for 6a (does the harness actually measure what it claims?) and the **template** for 6c (what must an agent-emitted strategy look like on disk?).

## Choice of reference strategy

**Constant-stake mean reversion on a single-market mid-price.**

Mechanism:
- Maintain a rolling window of the last `window_size` mid-prices (mid = (best_bid + best_ask) / 2).
- When `mid < mean - k * stddev`: emit a BACK signal at best_ask, stake = `stake_gbp`.
- When `mid > mean + k * stddev`: emit a LAY signal at best_bid, stake = `stake_gbp`.
- Otherwise: no signal. Position sizing is constant (no compounding); exit is implicit on opposite-side signal.

Why this over the two roadmap candidates:

| Option | Problem |
|---|---|
| Dutching on Betfair favourites | Requires multi-runner market metadata (which selection is the favourite?) that ingestion does not yet surface. Pulls in runner-enumeration scope. |
| Kalshi daily mean-reversion | Workable but we have no Kalshi historical corpus and `selection_id` is pinned `NULL` per Debt 4 until Kalshi ingestion is fixed. Tests would have to invent a shape that may diverge from real Kalshi ticks. |
| **Single-market mean reversion (venue-agnostic)** | Works on either venue's `MarketData` shape because it only touches `bids[0]` and `asks[0]`. Runs against synthetic ticks today with no historical corpus. Slots into either venue once a real corpus lands. |

**Parameters** (stored on `strategies.parameters` JSONB):
```
{
  "window_size": 30,
  "z_threshold": 1.5,
  "stake_gbp": "10",
  "venue": "betfair"
}
```

**Edge claim (tested):** on a mean-reverting synthetic series (random walk with a strong pull-to-mean term) the strategy should produce `total_pnl_gbp > 0` and `win_rate > 0.5`. On a trending series (random walk with drift) the strategy should produce `total_pnl_gbp < 0`. Both are asserted by integration tests — proving the harness discriminates. A rubber-stamp harness would score both as wins.

**P&L settlement for 6b:** still simplified — an opposite-side fill closes the prior position at the new fill price (delta P&L = entry_price - exit_price for BACK-then-LAY, symmetric for LAY-then-BACK). No market-close settlement, no commission. Real settlement is deferred to 6c or post-6c when a real corpus lands.

## Contract additions (other phases depend on these)

### Wiki frontmatter contract (authoritative)

Every file under `wiki/30-Strategies/*.md` uses this frontmatter. 6c will emit files satisfying it:

```yaml
---
title: "<human title>"
type: strategy
strategy-id: <slug>                    # matches the filename stem and registry.slug
venue: betfair | kalshi | cross-venue
status: hypothesis                     # initial; registry is the source of truth afterward
author-agent: claude-opus-4-7 | human
created: YYYY-MM-DD
updated: YYYY-MM-DD
module: backtest_engine.strategies.<module>   # dotted path to the StrategyModule
parameters:                            # literal YAML dict → strategies.parameters JSONB
  window_size: 30
  z_threshold: 1.5
  stake_gbp: "10"
tags: [strategy, <venue>, ...]
---
```

**Invariant:** `strategy-id` (frontmatter) == filename stem == `strategies.slug`. The loader uses the filename as the canonical key and rejects any file whose frontmatter `strategy-id` disagrees.

### Loader contract

```
load_strategy_from_wiki(
    wiki_path: Path,
    db: Database,
) -> Strategy
```

Parses the frontmatter, imports `module` via `importlib`, verifies it exports a callable `on_tick` (structural `StrategyModule` check), UPSERTs a `strategies` row keyed on `slug`. On a pre-existing row, only `parameters` and `wiki_path` are updated; `status` is never clobbered by the loader (status lives on the registry state machine, not on disk).

## File-by-file changes

### Task 6b.1 — Wiki frontmatter loader

**New file:** `services/strategy_registry/src/strategy_registry/wiki_loader.py`
**New file:** `services/strategy_registry/tests/test_wiki_loader.py`

Responsibilities:
- Parse YAML frontmatter from a `.md` file using an existing dependency if one is already in the lockfile (prefer `pyyaml` if already present; otherwise add it as a `strategy-registry` dep — do not re-invent frontmatter parsing).
- Validate: required keys `title`, `strategy-id`, `venue`, `module`, `parameters`; filename stem matches `strategy-id`.
- Call `importlib.import_module(frontmatter["module"])`, verify `hasattr(mod, "on_tick")` and that it is callable. Do NOT execute `on_tick` here — AST safety is 6c.
- UPSERT: if `slug` already exists in `strategies`, UPDATE `parameters = $1, wiki_path = $2, updated_at = now()`. Else INSERT a new row at `status='hypothesis'`.
- Return a `Strategy` (same model as `crud.get_strategy`).

**`crud.py` extension:** add `async def upsert_strategy(db, *, slug, parameters, wiki_path) -> Strategy`. Keep `create_strategy` intact — the loader uses `upsert_strategy` because wiki files can be re-loaded. `upsert_strategy` must NOT transition status; only the state machine does that.

**Tests:**
- Frontmatter parse happy path: a fixture `.md` in `tests/fixtures/wiki/<slug>.md` round-trips to a `Strategy` with correct slug + parameters.
- Frontmatter parse failure: filename/strategy-id mismatch → `ValueError`.
- Frontmatter parse failure: missing required key → `ValueError`.
- Module-import failure: `module: nonexistent.module` → `ModuleNotFoundError` (or wrap as a `StrategyLoadError`).
- Module-shape failure: module exists but no `on_tick` attr → `StrategyLoadError`.
- UPSERT integration (pytest.mark.integration): load once → registry row with `status='hypothesis'`; change `parameters` on disk, load again → same UUID, `parameters` updated, `status` unchanged.

**Done when:** `uv run pytest services/strategy_registry/tests -x` passes including the new wiki-loader suite.

### Task 6b.2 — Reference strategy module

**New file:** `services/backtest_engine/src/backtest_engine/strategies/mean_reversion.py`
**New file:** `services/backtest_engine/tests/strategies/__init__.py`
**New file:** `services/backtest_engine/tests/strategies/test_mean_reversion.py`

Module shape:
```
# module-level state is forbidden (purity invariant enforced by 6c).
# The rolling window is carried through params — the harness hands the same
# params dict back on every tick, so we mutate a list inside it.

def on_tick(snapshot: MarketData, params: dict, now: datetime) -> OrderSignal | None:
    window = params.setdefault("_window", [])
    ...
```

Note on purity: the roadmap's safety invariant says a strategy must be pure `(snapshot, params) -> signal | None`. Mutating `params["_window"]` is permitted because `params` is the explicit state channel; the module itself holds no globals, touches no disk, no network, no `os.environ`. 6c's AST walk must allow `params[...] =` and `params.setdefault`.

Behaviour:
1. Require `snapshot.bids` and `snapshot.asks` non-empty; else return `None`.
2. Compute `mid = (best_bid + best_ask) / 2`. Append to `params["_window"]` (create if missing). Trim to `params["window_size"]`.
3. If `len(window) < window_size`: return `None` (warmup).
4. Compute `mean` and `stddev` of the window. If `stddev == 0`: return `None` (degenerate).
5. `z = (mid - mean) / stddev`. If `z < -z_threshold`: BACK at best_ask. If `z > z_threshold`: LAY at best_bid. Else `None`.
6. Stake = `Decimal(str(params["stake_gbp"]))`. Price = best_ask (BACK) or best_bid (LAY).

**Tests:**
- Warmup: first `window_size - 1` ticks return `None`.
- Long signal: series converging from above mean, z < -threshold → BACK signal with correct stake/price.
- Short signal: symmetric LAY path.
- Degenerate: constant-price window → no signal.
- Missing book side: empty `bids` or `asks` → `None`.
- Params plumbing: re-entering `on_tick` with the same `params` dict accumulates window state correctly; the `_window` list is observable to the caller (this is the contract 6c needs to understand).

### Task 6b.3 — Wiki strategy file + registry seed

**New file:** `wiki/30-Strategies/mean-reversion-ref.md`

Populated with the template frontmatter:
```
strategy-id: mean-reversion-ref
venue: betfair
module: backtest_engine.strategies.mean_reversion
parameters:
  window_size: 30
  z_threshold: 1.5
  stake_gbp: "10"
  venue: "betfair"
```

Body: hypothesis paragraph, mechanism, expected edge & risk (including the "profitable on mean-reverting, unprofitable on trending" claim asserted in tests), and a `Backtest Results` section whose numbers 6b.5 will fill in.

**New file:** `scripts/seed_reference_strategy.py` — one-shot CLI that calls `wiki_loader.load_strategy_from_wiki(wiki_path, db)` for `mean-reversion-ref`. Wired into the `scripts/` package so `python -m scripts.seed_reference_strategy` works. Idempotent by virtue of the UPSERT in 6b.1.

**Test:** a smoke test in `services/strategy_registry/tests/test_wiki_loader.py` that loads the actual repo file (`wiki/30-Strategies/mean-reversion-ref.md`) — not a fixture — so the contract between the on-disk file and the loader is exercised in CI. Use `pathlib` to locate the repo root relative to the test file.

### Task 6b.4 — Orchestrator rewire to real reference strategy

**Edits:**
- `services/research_orchestrator/src/research_orchestrator/runner.py` — replace the inlined trivial strategy + rigged SyntheticSource with:
  1. A call to `strategy_registry.wiki_loader.load_strategy_from_wiki(REPO_ROOT / "wiki/30-Strategies/mean-reversion-ref.md", db)` to ensure the registry row exists.
  2. Build a `SyntheticSource` from a **mean-reverting** price series (helper `_build_mean_reverting_ticks(n_ticks=300, mean=2.00, pull=0.2, noise=0.05)` — deterministic, seeded). 300 ticks exercises the 30-tick warmup plus ~270 active ticks.
  3. Import the strategy module via the registry row's `parameters["_module"]` (the loader stashes the dotted path; or read the wiki frontmatter again — design decision during implementation).
  4. Call `workflow.run_backtest(strategy_id, strategy_module, params, source, time_range, db)`.
  5. Advance on `result["n_trades"] > 0 and result["total_pnl_gbp"] > 0` — stricter than 6a's placeholder. Remove the `TODO(6b)` comment added in 6a; 6b is landing now.
- `services/research_orchestrator/pyproject.toml` — add `strategy-registry` to deps (for `wiki_loader`). `strategy-registry` is already a dep; verify.
- `services/research_orchestrator/tests/test_runner_integration.py` — update the integration test:
  - Happy path (mean-reverting series): asserts strategy advances to `paper`, `total_pnl_gbp > 0`, `n_trades > 0`.
  - Negative path (trending series): asserts strategy REMAINS at `hypothesis` because `total_pnl_gbp <= 0`. Replace the `_SYNTHETIC_BEST_ASK = 1.60` patch from 6a with a trend-series synthetic.
- `services/research_orchestrator/tests/test_workflow.py` — no changes expected; delegate contract unchanged.

**Done when:**
- `uv run pytest services/research_orchestrator/tests -x` passes including both happy and negative paths.
- End-to-end smoke: `python -m scripts.seed_reference_strategy` populates the registry row, `python -m research_orchestrator run-once` runs the real mean-reversion strategy through the harness and advances to `paper` on the mean-reverting series.

### Task 6b.5 — Wiki write-back after backtest

**New file:** `services/research_orchestrator/src/research_orchestrator/wiki_writer.py`
**New file:** `services/research_orchestrator/tests/test_wiki_writer.py`

Responsibility: after a backtest run finishes and metrics are stored on `strategy_runs`, update the `wiki/30-Strategies/<slug>.md` file's `## Backtest Results` section + set `updated: YYYY-MM-DD` on the frontmatter. This keeps the Obsidian vault as a faithful mirror of the registry for human review.

Implementation shape:
```
def write_backtest_results(
    wiki_path: Path,
    run_metrics: dict,
    run_ended_at: datetime,
) -> None: ...
```

- Preserve the body above and below the `## Backtest Results` heading.
- Replace the bulleted list under that heading with:
  - `Period: run_metrics["started_at"]` → `run_metrics["ended_at"]`
  - `Trades: n_trades`, `Win rate: win_rate`, `Sharpe: sharpe`, `Total P&L: total_pnl_gbp`, `Max drawdown: max_drawdown_gbp`, `Ticks: n_ticks_consumed`
- Update the frontmatter `updated:` field (literal YAML edit, preserve key order).

**Integration:** `runner.run_once` calls `wiki_writer.write_backtest_results` after the advance decision. Do NOT call it from inside `workflow.run_backtest` — keep that function DB-only; disk I/O is orchestration.

**Tests:**
- Round-trip: load `mean-reversion-ref.md`, call `write_backtest_results` with a stub metrics dict, reload via `wiki_loader`, assert frontmatter/body integrity preserved and Backtest Results block updated.
- Idempotency: calling `write_backtest_results` twice with the same metrics produces byte-identical output modulo the `updated:` timestamp.

**Done when:** after `python -m research_orchestrator run-once` the wiki file's `## Backtest Results` block shows the latest run's numbers and `updated:` is today's date.

## Execution order

Strict: 6b.1 → 6b.2 → 6b.3 → 6b.4 → 6b.5. 6b.3 depends on 6b.1 (the loader has to exist to consume the wiki file) and 6b.2 (the `module:` in frontmatter has to resolve). 6b.4 depends on all three. 6b.5 depends on 6b.4 for the integration seam.

Each task commits before the next starts. Two-stage review (spec compliance then code quality) after each commit, per `/subagent-driven-development`.

## Out of scope for 6b (deferred)

- Real settlement (market-close P&L, commission). Still using same simplified delta-P&L on exit as 6a.
- AST safety walk on strategy modules — 6c owns it.
- Agentic strategy generation — 6c.
- Multiple reference strategies; 6b lands exactly one.
- Walk-forward / parameter sweeps.
- `mean-reversion-ref.md` advancing to `paper` trading against real market data (needs historical corpus — post-6c).
- Kalshi-specific contract mechanics (YES/NO, cents-price, Debt 4 `selection_id` handling) — the reference strategy is venue-agnostic; a Kalshi specialisation is a post-6b enhancement.

## Files touched summary

**New:**
- `services/strategy_registry/src/strategy_registry/wiki_loader.py`
- `services/strategy_registry/tests/test_wiki_loader.py`
- `services/strategy_registry/tests/fixtures/wiki/*.md`
- `services/backtest_engine/src/backtest_engine/strategies/mean_reversion.py`
- `services/backtest_engine/tests/strategies/__init__.py`
- `services/backtest_engine/tests/strategies/test_mean_reversion.py`
- `wiki/30-Strategies/mean-reversion-ref.md`
- `scripts/seed_reference_strategy.py`
- `services/research_orchestrator/src/research_orchestrator/wiki_writer.py`
- `services/research_orchestrator/tests/test_wiki_writer.py`

**Edited:**
- `services/strategy_registry/src/strategy_registry/crud.py` (add `upsert_strategy`)
- `services/research_orchestrator/src/research_orchestrator/runner.py`
- `services/research_orchestrator/tests/test_runner_integration.py`
- `services/strategy_registry/pyproject.toml` (pyyaml dep if not already present)

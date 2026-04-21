# Plan: Phase 6a — Backtest Harness + Historical Data Loader

> **Roadmap parent:** `docs/superpowers/plans/2026-04-20-phase6-7-roadmap.md`
> **Branch:** `phase6-edge-generation`

## Why now

The research orchestrator (`services/research_orchestrator/src/research_orchestrator/workflow.py:43-46`) currently returns `{"sharpe": 0.0, "total_pnl_gbp": 0.0, "n_trades": 0, "status": "stub"}` from `run_backtest()`. There is no historical corpus and no harness. Promotion theatre. 6a replaces the stub with a real harness that replays `MarketData` ticks through `simulator/fills.py::match_order` and computes P&L.

## Contract (authoritative interface — other phases depend on this)

**Strategy module contract (Phase 6b/6c will satisfy this):**

```
StrategyModule = Protocol:
    def on_tick(snapshot: MarketData, params: dict, now: datetime) -> OrderSignal | None
```

Pure function. No I/O, no `os.environ`, no network. 6c's safety check enforces this via AST walk; 6a only documents the contract.

**Harness contract:**

```
run_backtest(
    strategy: StrategyModule,
    params: dict,
    source: TickSource,
    time_range: tuple[datetime, datetime],
    starting_bankroll_gbp: Decimal = Decimal("1000"),
) -> BacktestResult
```

`BacktestResult` is a dict with fixed keys: `sharpe`, `total_pnl_gbp`, `max_drawdown_gbp`, `n_trades`, `win_rate`, `n_ticks_consumed`, `started_at`, `ended_at`. Shape matches the `strategy_runs.metrics` JSONB column so promotion is config-only.

**TickSource contract:**

```
TickSource = Protocol:
    async def iter_ticks(time_range) -> AsyncIterator[MarketData]  # timestamp-ordered
```

Two concrete implementations live in `services/backtest_engine/src/backtest_engine/sources/`:
- `ArchiveSource` — reads `market_data_archive` hypertable ordered by timestamp.
- `SyntheticSource` — in-memory list of MarketData for determinism tests.

## Determinism invariant (done-when condition)

`simulator/fills.py::match_order` currently stamps `ExecutionResult.timestamp = datetime.now(UTC)` (line 95) — non-deterministic. 6a **must** factor this through a `now_fn: Callable[[], datetime]` parameter (default `lambda: datetime.now(UTC)` for live/paper parity). The harness passes a clock that returns the tick's own timestamp, so two replays of the same tick sequence produce byte-identical `ExecutionResult`s modulo the UUID `order_id` (order_ids are ignored in metrics).

## File-by-file changes

### Task 6a.1 — DB migration: `market_data_archive` hypertable

**New file:** `scripts/db/migrations/0005_market_data_archive.sql`

Table shape:
- `venue` text (betfair|kalshi)
- `market_id` text
- `observed_at` timestamptz
- `bids` jsonb  (list of [price, size])
- `asks` jsonb
- `last_trade` numeric(10,4) nullable
- `ingested_at` timestamptz default now()

Primary key: `(venue, market_id, observed_at)` — deduplicates re-loads of the same TAR file.
TimescaleDB hypertable on `observed_at` with a sensible chunk interval (start with `INTERVAL '1 day'` — adjustable later).
Index on `(venue, market_id, observed_at DESC)` for the replay cursor.

**Done when:** `uv run python -m scripts.migrate` applies cleanly against a fresh DB and `\d+ market_data_archive` in psql shows the hypertable.

**Tests:** one integration test in `services/common/tests/test_migrations.py` (extend existing) that `CREATE`s a row, selects it back, and checks hypertable chunk creation.

### Task 6a.2 — Historical loader

**New file:** `services/ingestion/src/ingestion/historical_loader.py`
**New file:** `services/ingestion/tests/test_historical_loader.py`

Two modes, one entrypoint `load_archive(source: Literal["betfair_tar", "redis_xrange"], ...) -> int` (returns rows inserted):

- **`betfair_tar`** mode: accept a directory path and a venue label. For each `.tar` file, yield decoded `MarketData` objects. Betfair historical TAR format: each file is bz2 with one JSON line per tick (Betfair Exchange Stream API format). Decode via the existing adapter code — **reuse `ingestion/betfair_adapter.py` decode helpers**; if they're too tightly coupled to the live stream, extract the decode step into a small helper shared by both paths. Insert in 5000-row batches via `COPY` or `executemany`.
- **`redis_xrange`** mode: `XRANGE market.data - +` against the configured Redis, parse each entry's `json` field as `MarketData`, batch-insert. This lets us capture a live ingestion session into the archive.

Idempotency: `ON CONFLICT (venue, market_id, observed_at) DO NOTHING`.

Config additions in `algobet_common/config.py`:
- `historical_archive_dir: str | None`
- `historical_load_batch_size: int = 5000`

**Done when:** a fixture TAR with 100 synthetic ticks loads to a test DB and `SELECT COUNT(*)` returns 100. Second load returns 0 new rows.

**Tests:**
- Unit: TAR decode against a small fixture (create 2-3 ticks, tar+bz2, check decode returns expected MarketData).
- Integration: round-trip via test Postgres container (`pytest.mark.integration`).
- Unit: XRANGE mode with a fake Redis stream (use `fakeredis` if available, else skip-marked).

### Task 6a.3 — `backtest_engine` workspace member

**New directory:** `services/backtest_engine/`
**New files:**
- `services/backtest_engine/pyproject.toml`
- `services/backtest_engine/src/backtest_engine/__init__.py`
- `services/backtest_engine/src/backtest_engine/harness.py` — implements `run_backtest()` contract
- `services/backtest_engine/src/backtest_engine/sources/__init__.py`
- `services/backtest_engine/src/backtest_engine/sources/archive.py` — `ArchiveSource`
- `services/backtest_engine/src/backtest_engine/sources/synthetic.py` — `SyntheticSource`
- `services/backtest_engine/src/backtest_engine/metrics.py` — pure P&L / Sharpe / drawdown functions
- `services/backtest_engine/src/backtest_engine/strategy_protocol.py` — the `StrategyModule` Protocol
- `services/backtest_engine/src/backtest_engine/py.typed`
- `services/backtest_engine/tests/__init__.py`
- `services/backtest_engine/tests/test_harness.py`
- `services/backtest_engine/tests/test_metrics.py`
- `services/backtest_engine/tests/test_sources.py`

**Root `pyproject.toml` updates:**
- Add `"backtest-engine"` to `[project].dependencies`
- Add `backtest-engine = { workspace = true }` to `[tool.uv.sources]`
- Add `"services/backtest_engine"` to `[tool.uv.workspace].members`
- Add `"services/backtest_engine/tests"` to `[tool.pytest.ini_options].testpaths`

**Service `pyproject.toml`:** mirror simulator's — depend on `algobet-common` and `simulator` (for `match_order` + `Book`).

**Factoring `match_order` for determinism:** this is the one source-file edit outside the new service. Add a `now_fn: Callable[[], datetime] = lambda: datetime.now(UTC)` keyword-only parameter to `match_order` in `services/simulator/src/simulator/fills.py`. Update `services/simulator/src/simulator/engine.py` caller at line 136 to keep existing behaviour (default). Add a simulator test pinning that `now_fn` is honoured.

**Harness control flow:**
1. Create a `strategy_run` row via `crud.start_run(db, strategy_id, mode='backtest')`.
2. Instantiate a `Book` (reuse `simulator/book.py`).
3. Iterate `source.iter_ticks(time_range)`:
   - Book.update(tick)
   - `signal = strategy.on_tick(tick, params, now=tick.timestamp)`
   - If signal: `result = match_order(signal, tick, now_fn=lambda: tick.timestamp)`
   - Append `(tick.timestamp, result)` to an in-memory fill log
4. After loop: compute metrics via `metrics.py` functions.
5. Call `crud.end_run(db, run_id, metrics=result_dict)`.
6. Return `BacktestResult`.

**Metrics module (pure functions, unit-tested):**
- `total_pnl_gbp(fills, settlement_fn) -> Decimal` — settlement_fn maps filled (side, price, stake) → settled P&L at tick close. For 6a, use a trivial settlement: assume every filled order settles immediately at its own VWAP fill price (so P&L = 0 for matched markets). 6b/6c replace this with real settlement when a reference strategy lands.
- `sharpe(per_tick_pnl_series) -> float` — daily-bucketed if span > 1 day, else tick-level. Annualised factor 252.
- `max_drawdown_gbp(equity_curve) -> Decimal`
- `win_rate(fills) -> float`

**Trivial winning strategy for determinism test:** bundle a `services/backtest_engine/tests/fixtures/always_back_below_two.py` that returns a BACK signal whenever best ask is ≤ 1.50. Feed a `SyntheticSource` of 100 ticks all at best ask 1.40. Assert `n_trades > 0` and that two consecutive runs produce identical `BacktestResult` dicts (structural equality on every key).

**Done when:**
- `uv run pytest services/backtest_engine/tests` passes.
- `run_backtest(trivial_strategy, {}, SyntheticSource(ticks), time_range)` called twice yields equal `BacktestResult` dicts.
- The `strategy_runs` row exists with `mode='backtest'`, `metrics` populated, `ended_at NOT NULL`.

### Task 6a.4 — Orchestrator rewire

**Edits:**
- `services/research_orchestrator/src/research_orchestrator/workflow.py:43-46` — replace stub. New signature:
  `async def run_backtest(strategy_id: UUID, strategy: StrategyModule, params: dict, source: TickSource, time_range, db: Database) -> BacktestResult`
  The orchestrator is still free to call the **old stub signature** for tests that don't want to wire a harness. Keep a thin `run_stub_backtest()` for those callers and rename this one explicitly. Delete the stub path in `runner.py` so the production loop uses the real harness.
- `services/research_orchestrator/src/research_orchestrator/runner.py` — update `run_once` to build a `SyntheticSource` + a trivial strategy (same fixture used in 6a.3 tests) for now. 6b replaces this with a real strategy.
- `services/research_orchestrator/pyproject.toml` — add `backtest-engine` dependency.
- `services/research_orchestrator/tests/test_workflow.py` + `test_runner_integration.py` — update to match the new signature; the existing "advance hypothesis → backtesting → paper" assertion still holds because the backtest call returns a dict without a `status='stub'` field. Change the advancement trigger to `result["n_trades"] > 0` OR `result["sharpe"] is not None` — whichever the existing tests most naturally accommodate.

**Done when:**
- `uv run pytest services/research_orchestrator/tests` passes.
- End-to-end smoke: `python -m research_orchestrator run-once` creates a strategy, runs a backtest via the harness against synthetic ticks, inserts a `strategy_runs` row with real metrics, and advances `hypothesis → backtesting → paper`.

## Execution order

Strict: 6a.1 → 6a.2 → 6a.3 → 6a.4. Each task merges (commits) before the next starts. 6a.3 depends on 6a.1 (table must exist for `ArchiveSource` integration test) and 6a.2 (so the integration test can seed rows via the loader). 6a.4 depends on 6a.3.

## Out of scope for 6a (deferred to 6b/6c/later)

- Real settlement logic (uses trivial immediate-fill P&L; 6b will introduce market-close settlement for the reference strategy).
- Walk-forward optimisation.
- Real Betfair historical corpus purchase/download — 6a only proves the loader works against a synthetic TAR fixture.
- AST safety check on strategy modules — moved to 6c.
- Parameter sweeps, grid search.

## Files touched summary

**New:**
- `scripts/db/migrations/0005_market_data_archive.sql`
- `services/ingestion/src/ingestion/historical_loader.py`
- `services/ingestion/tests/test_historical_loader.py`
- `services/backtest_engine/**` (new workspace member, ~12 files)

**Edited:**
- `services/simulator/src/simulator/fills.py` (add `now_fn` param)
- `services/simulator/src/simulator/engine.py` (caller unchanged behaviourally; verify)
- `services/simulator/tests/test_fills.py` (pin `now_fn`)
- `services/common/src/algobet_common/config.py` (historical_archive_dir etc.)
- `services/research_orchestrator/src/research_orchestrator/workflow.py`
- `services/research_orchestrator/src/research_orchestrator/runner.py`
- `services/research_orchestrator/tests/test_workflow.py`
- `services/research_orchestrator/tests/test_runner_integration.py`
- `services/research_orchestrator/pyproject.toml`
- `pyproject.toml` (workspace + testpaths)

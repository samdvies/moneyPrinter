# Roadmap: Phase 6 (edge generation) + Phase 7 (live execution)

> **Type:** roadmap (not an execution plan). Each sub-phase (6a, 6b, 6c, 7a…7e) gets its own plan doc written when its turn comes. This document exists so any Claude instance (or the human) can get oriented without re-deriving the decomposition.

## Context

Phase 5b merged to `main` on 2026-04-20 (`5203890`). All plumbing phases 1 → 5b are shipped:

| Phase | Status | What it gave us |
|---|---|---|
| 1 | ✓ | `uv` workspace, Docker (Postgres+Redis), migrations, CI, `algobet_common` |
| 2a/2b | ✓ | Betfair + Kalshi ingestion → `market.data` |
| 3a | ✓ | Paper-trading simulator (deterministic matching) |
| 3b | ✓ | Strategy registry CRUD + lifecycle state machine |
| 4a | ✓ | Risk manager pre-flight checks |
| 4b | ✓ | Dashboard skeleton + read-only views |
| 4c | ✓ | Research orchestrator **scaffold** (206 lines, stubs) |
| 5a | ✓ | Cumulative exposure + advisory locks |
| 5b | ✓ | Dashboard auth: argon2id + Redis sessions + CSRF |

Post-5b devil's-advocate sweep landed 3 cheap fixes on top of 5b (fail-closed `DASHBOARD_ALLOWED_ORIGINS`, struck `DASHBOARD_INSECURE_COOKIES` vapourware, cookie-flag + csrf-rotation test pins). Residual debts 8-15 logged in `wiki/20-Risk/open-debts.md`.

**What is missing to generate real edges and place real money:**

- Research orchestrator `hypothesize()` → hardcoded stub; `run_backtest()` → zeros. No historical-data corpus, no backtest harness. `wiki/30-Strategies/` is empty.
- No `execution/` crate yet. CLAUDE.md architecture lists a Rust execution engine; it doesn't exist on disk. Debt 2 in the open-debts ledger names the gap.

---

## Phase 6 — Edge Generation

### Why it's the next phase

The research loop today can promote strategies through `hypothesis → backtesting → paper → retired` but every transition is theatre: the hypothesis is hardcoded, the backtest returns zeros, and no strategy has ever run on real market data because there's no backtest harness to run it against. Real edge generation has four parts, in strict dependency order:

1. **Historical data corpus** — nothing exists.
2. **Backtest harness** — the simulator's matching engine driven by a replay source instead of Redis.
3. **One hand-written reference strategy** — ground truth for the harness + template for step 4.
4. **Agentic hypothesis generation** — the LLM (xAI Grok, OpenAI-compatible SDK) generates strategy specs; harness evaluates them.

Starting step 4 before step 3 is building a strategy generator with nothing to evaluate its output.

### Phase 6a — Backtest Harness + Historical Data Loader

**Canonical plan:** `docs/superpowers/plans/2026-04-2x-phase6a-backtest-harness.md` (write when 6a begins).

Contract: `run_backtest(strategy_module, source, time_range) → {sharpe, total_pnl_gbp, max_drawdown_gbp, n_trades, ...}` — identical shape to paper/live so promotion is a config change, not a code change (per CLAUDE.md "paper API ≡ live API" invariant).

New modules:
- `services/backtest_engine/` — new uv workspace member; thin driver around the simulator.
- `services/ingestion/src/ingestion/historical_loader.py` — pulls Betfair historical TAR files (or replays captured live `market.data` via Redis `XRANGE`) into a new `market_data_archive` TimescaleDB hypertable.
- `scripts/db/migrations/0005_market_data_archive.sql`.

Reuses `services/simulator/engine.py::match_order` — the matching primitive is already correct; we only change the market-data source.

**Done when:** a synthetic 1h tick series + a known-winning trivial strategy produces `total_pnl_gbp > 0` across two runs with identical metrics (determinism pin).

### Phase 6b — Reference Strategy + Wiki↔Registry Wiring

**Canonical plan:** `docs/superpowers/plans/2026-04-2x-phase6b-reference-strategy.md`.

Write **one** hand-coded strategy — simplest credible choice: constant-stake Dutching on Betfair horse-racing favourites, or a Kalshi mean-reversion on daily contracts. Wire `wiki/30-Strategies/<slug>.md` frontmatter (hypothesis, parameter space, risk notes) to a registry row and a Python module.

Run it through the 6a harness. Declare success when:
- Sharpe + P&L numbers are plausible (not necessarily profitable).
- Two consecutive backtest runs produce identical metrics.
- The registry row is correctly populated with `status='backtesting'`, then transitions to `paper` via `orchestrator.promote()`.

This phase is the **ground truth** for 6a and the **template** for 6c.

### Phase 6c — Agentic Hypothesis Generation

**Canonical plan:** `docs/superpowers/plans/2026-04-2x-phase6c-agentic-hypothesis.md`.

Replace `workflow.hypothesize()` with an xAI Grok chat-completions call (OpenAI-compatible SDK) that:
- Reads `wiki/10-Foundations/` + recent `market_data_archive` stats.
- Emits a strategy spec in the 6b format (frontmatter + Python skeleton).
- Writes `wiki/30-Strategies/<slug>.md`, registers a row with `status='hypothesis'`.

Orchestrator then runs 6a harness → `promote()` to `backtesting` → `paper` per existing state machine. Human approval still gates `paper → awaiting-approval → live`.

**Safety invariant:** the agent cannot write a strategy module that calls out to the network, disk, or `os.environ` — the reference strategy template should already be structured so that a strategy module is pure `(market_snapshot, params) → OrderSignal | None`. Enforce via a static check (ruff plugin or simple AST walker) in the harness entry point.

---

## Phase 7 — Live Execution (Rust)

### Why it's the final phase

Once a paper strategy has been approved via the dashboard, the only thing between it and real money is the execution engine. It doesn't exist yet. CLAUDE.md reserves the hot path for Rust (`execution/` crate) for latency reasons — Betfair's `/placeOrders` endpoint is tenths-of-a-second round-trip in London; a Python client introduces GIL jitter that a market-making strategy can't absorb. Phase 7 is the only place real capital is at risk, so the promotion gate is strictest here.

**Not-negotiable invariants** (inherit from CLAUDE.md + existing risk manager):
- Paper API ≡ live API: the `execution.results` publisher must emit messages indistinguishable in shape from the simulator's.
- No order goes out without a matching approved signal on `order.signals.approved` published by the risk manager.
- Independent exposure cap in the Rust engine (Debt 2) — defence in depth if the risk manager is misconfigured or bypassed.
- Kill switch on `risk.alerts`: on any `severity=critical` message, cancel all open orders and refuse new placements until manual reset.
- Idempotency on `order_id`: a re-delivered approval must not place a duplicate order.
- Dry-run mode: staging can drive live venue auth + REST calls without placing orders (separate API endpoint or `--dry-run` flag).

### Phase 7a — Rust Workspace + Betfair REST Client

**Canonical plan:** `docs/superpowers/plans/2026-04-2x-phase7a-execution-scaffold.md`.

Create `execution/` at repo root as a Cargo workspace (not in `services/` — different toolchain). Members: `execution-core` (venue-agnostic types), `execution-betfair` (API client), `execution-bin` (binary).

Dependencies: `tokio`, `reqwest` with `rustls-tls`, `serde`, `serde_json`, `tracing`, `redis` (async), `sqlx` (optional — reconciliation), `uuid`.

Implement Betfair primitives as pure functions (no stream consumer yet):
- `login_cert(certs_dir, username, password, app_key) → SessionToken` (Betfair certificate login).
- `place_order(token, market_id, selection_id, side, size, price) → PlaceInstructionReport`.
- `cancel_order(token, market_id, bet_id) → CancelExecutionReport`.
- `list_current_orders(token) → Vec<CurrentOrder>`.

Add `make_execution_test` target that runs against Betfair's **developer sandbox** (not live) via env-gated credentials. CI does not run this; it's a local/staging-only smoke.

**Done when:** `cargo test -p execution-betfair --features sandbox` places + cancels an order on the Betfair developer sandbox and asserts both the place and cancel reports deserialise correctly.

### Phase 7b — Signal Consumer + Execution Results Publisher

**Canonical plan:** `docs/superpowers/plans/2026-04-2x-phase7b-signal-consumer.md`.

Bind the 7a primitives to the Redis bus:
- Consumer group on `order.signals.approved` → deserialise → call `place_order` → publish `ExecutionResult` on `execution.results`.
- Reuse consumer-group semantics from the simulator (same `consumer_group_name` pattern, per-service offsets).
- Fill stream subscriber: Betfair's `order/change` stream → publish `fill` events on `execution.results` with the same shape the simulator emits.
- Idempotency: use `order_id` as the external order reference (`customer_order_ref` on Betfair, `client_order_id` on Kalshi). Reject a re-delivered approval whose `order_id` already appears in `orders` as `placed` or `filled`.

**Done when:** an end-to-end smoke test on sandbox places an order from a manually-injected approved signal, the Redis `execution.results` stream shows a `placed` event, the fill stream produces a `filled` event, and the `orders` table ends with `status='filled'`.

### Phase 7c — ForecastEx Parity (replaces Kalshi, 2026-04-21)

**Canonical plan:** `docs/superpowers/plans/2026-04-2x-phase7c-forecastex-execution.md`.

**Venue pivot:** Kalshi's 23 October 2025 Member Agreement lists the UK as a Restricted Jurisdiction (no "Kalshi Global" carve-out), so the original "Kalshi parity" target is not executable for a UK-resident operator. ForecastEx (Interactive Brokers, CFTC-regulated, UK-accessible via IB) replaces it as the second non-sports venue. Market scope is narrow: US macro indicators, politics, climate. Canonical rationale in `wiki/20-Markets/Venue-Strategy.md`.

Add `execution-forecastex` crate alongside `execution-smarkets`. ForecastEx is accessed through the IB ecosystem — either TWS (Trader Workstation) + IB Gateway over the native IB API, or the IBKR Client Portal Web API (REST). Primitives to wrap: session auth, place order, cancel order, list fills, position reconciliation. Reuse the same `order.signals.approved` consumer — the `venue` field on the signal (`forecastex`) routes to the correct backend.

The `services/ingestion/src/ingestion/kalshi_adapter.py` scaffold stays in-tree as reference only (documents the venue-adapter pattern) but is not extended. Kalshi's `selection_id` treatment (Debt 4) is moot under this pivot; the same NULL-at-ingestion workaround note remains in the debt ledger for any future revisit.

**Revisit trigger for Kalshi:** user establishes non-UK residency or a US legal entity with a US-resident officer. Not scheduled.

### Phase 7d — Independent Exposure Cap + Kill-Switch Reaction

**Canonical plan:** `docs/superpowers/plans/2026-04-2x-phase7d-execution-safety.md`.

Closes Debt 2. Adds in the Rust engine:
- Per-strategy `max_exposure_gbp` check read from `strategies` table (or a cached copy refreshed every 60s). Rejects any placement that would breach; emits `RiskAlert` with `source='execution-engine'` and `severity='critical'`.
- Kill-switch consumer on `risk.alerts`: any `severity='critical'` message triggers `cancel_all_open_orders()` across both venues and sets an in-process flag that blocks new placements. Manual unlock via CLI flag + operator email check against the `operators` table.
- Reconciliation loop every 30s: compare local `orders` table vs. `list_current_orders` on each venue; emit `RiskAlert` on any discrepancy.

**Promotion-gate-auditor dispatch is mandatory** before the 7d merge.

### Phase 7e — First Live Money (Operational Playbook)

**Canonical plan:** `docs/superpowers/plans/2026-04-2x-phase7e-go-live-checklist.md`.

This is not a code phase — it's the operational dress-rehearsal before flipping any strategy to `live`. Checklist:

1. Paper-trade the strategy for ≥ 2 weeks without breaching cumulative exposure.
2. Dry-run the execution engine against the live Betfair/Kalshi endpoints (auth only, no placement) for ≥ 1 week.
3. £10 live test: promote a strategy with `max_exposure_gbp=10`, verify full round-trip (place → fill → settle → registry run row).
4. £100 live test: same, with `max_exposure_gbp=100`. Observe kill-switch behaviour by manually publishing a `severity=critical` RiskAlert.
5. £1000 live only after the £100 test has run for a week and all RiskAlerts have been triaged.

Phase 7e ends with the first strategy in `status='live'` and a signed operator decision log.

---

## Critical Files (Next Action Only — Phase 6a kickoff)

- `docs/superpowers/plans/2026-04-2x-phase6a-backtest-harness.md` (new — written when 6a begins)
- `services/backtest_engine/` (new workspace member; created during 6a)
- `services/ingestion/src/ingestion/historical_loader.py` (new; 6a)
- `scripts/db/migrations/0005_market_data_archive.sql` (new; 6a)
- `services/research_orchestrator/src/research_orchestrator/workflow.py:43-46` (swap stub for harness call during 6a)

## Reusable Utilities Already in the Codebase

- `services/simulator/engine.py::match_order` — driven in batch by the backtest harness.
- `strategy_registry.crud.transition` — the lifecycle gate.
- `strategy_registry.models.Strategy` — the row shape (metrics via `strategy_runs`).
- `algobet_common.bus.BusClient` — for `research.events`, not the backtest hot loop.
- `algobet_common.config.Settings` — extend; do not duplicate.
- `wiki/90-Templates/Strategy-Template.md`, `Paper-Summary-Template.md` — reuse.

## Out of Scope (explicitly deferred)

- Walk-forward optimisation / parameter sweeps (post-6c).
- Multi-strategy portfolio optimisation (post-7e).
- Dashboard MFA + audit log (Debts 6, 7).
- Kalshi YES/NO liability-math fix (Debt 4) — latent until Kalshi ingestion starts populating `selection_id`.
- Multi-operator RBAC, API tokens, TLS-termination story.
- Polymarket — UK geoblock + crypto CGT keep it off the roadmap.

## Dependency Graph (one-glance)

```
                ┌──────────────────┐
                │ 6a backtest     │
                │ harness + data  │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ 6b reference    │
                │ hand-coded      │
                │ strategy        │
                └────────┬─────────┘
                         │
           ┌─────────────┴─────────────┐
           ▼                           ▼
  ┌────────────────┐          ┌───────────────────┐
  │ 6c agentic    │          │ 7a rust scaffold +│
  │ hypothesis    │          │ betfair primitives│
  └───────┬────────┘          └────────┬──────────┘
          │                            │
          │                            ▼
          │                   ┌────────────────────┐
          │                   │ 7b signal consumer │
          │                   │ + fill publisher   │
          │                   └────────┬───────────┘
          │                            │
          │                            ▼
          │                   ┌────────────────────┐
          │                   │ 7c forecastex      │
          │                   │ (replaces kalshi)  │
          │                   └────────┬───────────┘
          │                            │
          │                            ▼
          │                   ┌────────────────────┐
          │                   │ 7d exposure cap +  │
          │                   │ kill switch        │
          │                   └────────┬───────────┘
          │                            │
          └────────────┬───────────────┘
                       ▼
              ┌─────────────────┐
              │ 7e go-live      │
              │ checklist (ops) │
              └─────────────────┘
```

**Earliest parallelisation point:** 6c and 7a can proceed in parallel after 6b, since 6c does not touch `execution/` and 7a does not touch the research loop. 7e cannot start until both arms converge.

## Answer in one paragraph

Phase 5b shipped today. The next two phases are **Phase 6 — edge generation** (6a backtest harness → 6b reference strategy → 6c agentic hypothesis) and **Phase 7 — live execution in Rust** (7a crate scaffold → 7b signal consumer → 7c ForecastEx parity [replaces Kalshi per 2026-04-21 venue review] → 7d exposure cap + kill-switch → 7e go-live checklist). 7a-d are code phases; 7e is operational. No live capital before 7e, no 6c before 6a+6b, no 7b before 6b.

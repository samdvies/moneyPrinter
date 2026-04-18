# Project Context — algo-betting

Agentic, low-latency algorithmic betting ecosystem targeting Betfair Exchange and Kalshi. Hobbyist tier. UK-based operator. Self-improving research loop with human-in-the-loop capital deployment.

## Ground Rules

- **No live capital without explicit human approval.** The promotion path is hypothesis → backtest → paper trading → **user review gate** → live. Never bypass the gate.
- **Paper trading API must match live execution API exactly.** Strategies must not know if they are in sim or live. Promotion is a config change, not a code change.
- **Risk-averse with real money.** Default max £1,000 exposure per strategy until proven over extended paper trading. The user specified they would "need to be very confident in a strategy to put in more than 1000."
- **Research is unconstrained; execution is gated.** Agents can go wild in simulation. They cannot place real orders autonomously.
- **UK legal scope only** — Betfair + Kalshi. Polymarket is deferred (UK geoblock + crypto CGT overhead). Do not add Polymarket integration without discussing the legal constraints.

## Tech Stack

- Python for research, ML, ingestion, risk, simulation, dashboards
- Rust for the execution hot path (order placement, fill management)
- Redis Streams as the message bus
- Postgres (TimescaleDB) for time-series market data + strategy registry
- Obsidian vault at `wiki/` as the knowledge base — research agents should read from and write into it

## Architecture — Event-Driven Microservices

Services talk over Redis Streams. Topics: `market.data`, `order.signals`, `execution.results`, `research.events`, `risk.alerts`.

Core services:
1. **Ingestion** (Python) — Betfair streaming + Kalshi REST/WebSocket → `market.data`
2. **Simulator** (Python) — consumes `market.data`, exposes paper-trading order API identical to live
3. **Research Orchestrator** (Python + Claude API) — generates hypotheses, runs backtests, evaluates, promotes
4. **Strategy Registry** (Postgres) — strategy lifecycle state, parameters, performance
5. **Risk Manager** (Python) — pre-flight checks, exposure limits, kill switch
6. **Execution Engine** (Rust) — live order placement to Betfair + Kalshi (gated by risk manager + human approval)
7. **Dashboard** (FastAPI) — approve/reject, monitor P&L, observe research agent activity

## Wiki Conventions

- Every note uses YAML frontmatter with `title`, `type`, `tags`, `updated`, `status`.
- Research agents write daily logs to `wiki/70-Daily/YYYY-MM-DD.md`.
- Strategy notes live under `wiki/30-Strategies/` with a standard template (hypothesis, backtest results, paper P&L, approval status).
- Foundations (Karpathy content, market microstructure basics) live under `wiki/10-Foundations/`.

## Key References

- `docs/superpowers/specs/` — full design docs
- `wiki/00-Index/README.md` — wiki entry point

## Commit Discipline

Per user default: only commit when asked. Do not auto-commit.

## Plan Documents

Plan documents under `docs/superpowers/plans/` describe **what** to do and **why** — file paths, responsibilities, interfaces between tasks, verification steps. They do **not** embed complete code. Short contract snippets (a type signature, a single schema row, one config key) are fine; full functions, full migrations, full workflow YAML, full `pyproject.toml` contents are not. Code belongs in the execution diff, not the plan.

## Phase 1 Status

Scaffolding complete. The following exists:

- `docker compose up` runs TimescaleDB + Redis locally
- `uv run python -m scripts.migrate` applies SQL migrations (strategies / strategy_runs / orders)
- `algobet_common` package: Settings, pydantic schemas (MarketData, OrderSignal, ExecutionResult, RiskAlert), BusClient (Redis Streams), Database (asyncpg pool)
- `ingestion` service is a hello-world publisher. Real Betfair/Kalshi code is Phase 2.
- CI runs lint + typecheck + tests + end-to-end smoke on push.

Every subsequent service (simulator, risk manager, orchestrator, dashboard, execution-engine) should be a new member of the uv workspace under `services/` and reuse `algobet_common`. Never re-implement bus or DB logic in a service.

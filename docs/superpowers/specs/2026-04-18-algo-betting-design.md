---
title: algo-betting — System Design
date: 2026-04-18
status: draft
---

# algo-betting — System Design

## Context

We are building an agentic, low-latency statistical arbitrage ecosystem targeting Betfair Exchange and Kalshi. The operator is a UK-based hobbyist with £500–£5,000 starting capital, risk-averse in live deployment (≤£1,000 per strategy without strong evidence), and willing to let agents experiment freely in simulation.

The long-term goal is a self-improving research flywheel in the style of Karpathy's "LLM wiki" pattern: agents propose hypotheses, backtest them against historical data, promote winners to paper trading, and surface the best candidates for human approval before any live capital is committed. Research compounds over time via a persistent Obsidian-backed knowledge base.

This design is Phase 0's artefact — the architectural spec from which we will draft an implementation plan.

## Invariants

1. **Promotion requires human approval.** The path is `hypothesis → backtest → paper → human review → live`. The gate between paper and live is never automated.
2. **Paper trading API must match live execution API exactly.** Strategies are venue-config, not code-config. Promotion from sim to live is a flag change.
3. **Two-layer risk enforcement.** Python risk manager as a policy layer; Rust execution engine as a hard cap.
4. **Sources are immutable.** The wiki is derived. Raw sources in `wiki/80-Sources/` are never edited.
5. **UK legal scope only.** Betfair + Kalshi. No Polymarket without explicit reconsideration.

## Architecture

Event-driven microservices communicating over Redis Streams. Python for research / ML / ingestion / risk / sim / dashboard. Rust for the execution hot path.

```
                      ┌────────────────────────┐
                      │   Redis Streams (bus)  │
                      │  topics: market.data,  │
                      │  order.signals,        │
                      │  execution.results,    │
                      │  research.events,      │
                      │  risk.alerts           │
                      └──┬──┬──┬──┬──┬──┬──────┘
                         │  │  │  │  │  │
          ┌──────────────┘  │  │  │  │  └───────────────┐
          │                 │  │  │  │                  │
          ▼                 ▼  ▼  ▼  ▼                  ▼
   ┌────────────┐   ┌───────────┐  ┌──────────┐   ┌────────────┐
   │ Ingestion  │   │ Research  │  │  Risk    │   │ Execution  │
   │  (Python)  │   │Orchestr.  │  │ Manager  │   │  (Rust)    │
   │ betfair-   │   │ (Python+  │  │ (Python) │   │  live &    │
   │ lightweight│   │  Claude)  │  │          │   │  gated     │
   │ kalshi SDK │   │           │  │          │   │            │
   └─────┬──────┘   └─────┬─────┘  └────┬─────┘   └─────┬──────┘
         │                │             │               │
         ▼                ▼             ▼               ▼
   ┌────────────────────────────────────────────────────────┐
   │   PostgreSQL + TimescaleDB (market data, strategies,    │
   │   performance, lifecycle state) + Obsidian wiki vault   │
   └────────────────────────────────────────────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │    Dashboard     │
                       │   (FastAPI +     │
                       │    lightweight   │
                       │    web UI)       │
                       │  approve/reject, │
                       │  monitor P&L     │
                       └──────────────────┘
```

## Services

### 1. Ingestion (Python)

**Responsibility:** real-time market data + historical backfill.

- Betfair Exchange Stream API via `betfairlightweight` (≥480★, active) — ticker, order book snapshots, markets lifecycle
- Kalshi via official Python SDK + WebSocket — order book, trades
- Historical backfill from Betfair Data Scientists' archive (1.5TB) for backtests
- Publishes to `market.data` topic with schema `{venue, market_id, timestamp, bids, asks, last_trade}`
- Writes raw ticks to TimescaleDB hypertable partitioned by (venue, day)

**Reuse:** `betfairlightweight`, Kalshi official SDK.

### 2. Market Simulator (Python)

**Responsibility:** a paper-trading venue with the same order-placement API as live execution.

- Subscribes to `market.data`
- Maintains a virtual order book per market, models:
  - Fees (Betfair commission tier, Kalshi 3%)
  - Slippage against order-book depth
  - Partial fills
  - Queue position for limit orders (approximation)
- Exposes an order API identical to the Execution Engine's. A strategy publishes to `order.signals` with a `mode: paper|live` flag. The Simulator consumes `paper`; the Execution Engine consumes `live`.
- Tracks virtual P&L, positions, exposure per strategy
- Emits `execution.results` events that look identical to live fills

**Reuse:** `flumine`'s simulation harness as reference implementation.

### 3. Research Orchestrator (Python + Claude API)

**Responsibility:** the research flywheel. This is the self-improving core.

- Periodic loop:
  1. Read the wiki (`wiki/10-` through `wiki/40-`) for context
  2. Read recent market data summaries
  3. Ask Claude: "given X, what hypothesis would you test?"
  4. Generate backtest code (constrained to a strategy template)
  5. Run backtest against historical data
  6. Evaluate results against thresholds (CLV, Sharpe, drawdown)
  7. If passes → promote to paper trading, write `30-Strategies/<id>.md` page
  8. If fails → write reasoning to today's `70-Daily/YYYY-MM-DD.md`
  9. Update wiki: ingest any new findings into `10-Foundations/` and cross-link
- Also runs the **Wiki Maintenance Agent** modes (ingest / query / lint — see `wiki/60-Agents/Wiki-Maintenance-Agent.md`)

**Models:**
- Hypothesis generation and code synthesis: Claude Sonnet 4.6 (quality)
- Linting and summarisation: Claude Haiku 4.5 (cost)
- Caching: prompt cache on the wiki context for efficiency

**Reuse:** ryanfrigo/kalshi-ai-trading-bot multi-agent structure as reference. OctagonAI's 5-gate risk structure for backtest evaluation criteria.

### 4. Strategy Registry (Postgres)

**Responsibility:** source of truth for strategy lifecycle.

Schema:
```sql
strategies (
  id uuid pk,
  slug text unique,            -- e.g. "betfair-racing-preoff-scalp-v1"
  status text,                 -- hypothesis|backtesting|paper|awaiting-approval|live|retired
  parameters jsonb,
  created_at, updated_at, approved_at, approved_by,
  wiki_path text               -- link to 30-Strategies/...md
)

strategy_runs (
  id, strategy_id, mode (backtest|paper|live),
  started_at, ended_at,
  metrics jsonb  -- pnl, clv, sharpe, drawdown
)

orders (
  id, strategy_id, run_id, mode,
  venue, market_id, side, stake, price,
  placed_at, filled_at, filled_price, status
)
```

Single source of truth. The wiki page for each strategy references its registry row.

### 5. Risk Manager (Python)

**Responsibility:** policy-layer enforcement for both paper and live signals.

- Subscribes to `order.signals`
- Pre-flight checks:
  - Per-strategy max exposure (default: £1,000 live, £10,000 paper)
  - Per-market max exposure
  - Portfolio-wide drawdown kill-switch (trigger: -10% intraday)
  - Kelly-fraction sanity (reject sizes >½-Kelly of declared edge)
  - Strategy status check (is it approved for the requested mode?)
- **Approves → forwards** to `order.signals.approved`. **Rejects → emits** `risk.alerts` and drops.
- Live execution consumes only `order.signals.approved`.
- Emits heartbeat `risk.alerts` with current exposure summaries for the dashboard.

### 6. Execution Engine (Rust)

**Responsibility:** fast, correct order placement against Betfair + Kalshi.

- Subscribes to `order.signals.approved` where `mode=live`
- Places orders via REST / streaming APIs
- Handles state machine: placed → partially_filled → filled | cancelled | rejected
- Hard cap: rejects any order whose `stake > $HARD_CAP` even if the risk manager approved it (defence in depth)
- Emits `execution.results`

**Why Rust:** the Python tier already does real work (risk, sim, research). Keeping the live-order path in Rust gives us:
- Predictable GC-free latency
- Memory safety for a path that moves real money
- An isolation boundary — the execution binary is small, auditable, and does one thing

**Reuse:** We're not aware of a dominant Rust Betfair/Kalshi client yet. Likely hand-rolled. Consider writing async Rust with `tokio` + `reqwest` + `tungstenite`.

### 7. Dashboard (FastAPI + minimal frontend)

**Responsibility:** the human's window into the system.

- Lists strategies by status
- Shows paper + live P&L
- **Approve / reject** buttons for strategies in `awaiting-approval`
- Current exposure view
- Research agent activity feed (from `research.events`)
- Kill switch

Minimal frontend — HTMX or Svelte. Not a differentiator; it exists so you can approve strategies quickly and see what's happening.

## Data Flow Examples

### Paper trade cycle

```
Ingestion → market.data → Strategy (running in Orchestrator)
                        → order.signals (mode=paper) → Risk Manager
                        → order.signals.approved → Simulator
                        → execution.results → Strategy Registry + dashboard
```

### Live trade cycle (post-human-approval)

```
Ingestion → market.data → Strategy (running in Orchestrator)
                        → order.signals (mode=live) → Risk Manager
                        → order.signals.approved → Execution Engine
                        → Betfair / Kalshi API → execution.results → Registry + dashboard
```

### Research loop

```
Orchestrator loop (every N minutes):
  1. Query wiki + registry for context
  2. Claude → hypothesis
  3. Claude → backtest code
  4. Run backtest on historical data (Timescale)
  5. Evaluate → decision
  6. Write strategy page + daily log
  7. If passes → register with status=paper, begin paper runs
```

## The Wiki (Karpathy Pattern)

`wiki/` is an Obsidian vault following Karpathy's LLM-wiki pattern (see `wiki/10-Foundations/Karpathy-LLM-Wiki.md`).

- Sources (immutable) in `80-Sources/`
- Derived pages (synthesised) in `10-` through `70-`
- Schema in `CLAUDE.md` + `wiki/00-Index/README.md`
- Research Orchestrator acts as the maintainer: ingests new findings, updates cross-links, writes daily logs

The wiki is **both the agent's notebook and its memory**. Without it, research resets every loop. With it, research compounds.

## Infrastructure

Following `wiki/50-Infrastructure/Hosting-Strategy.md`:

- **Phase 0–2 (£30–50/mo)**: Oracle Cloud Always Free for research/ML + Hetzner Frankfurt cx22 for Betfair execution + QuantVPS Chicago entry tier for Kalshi execution
- **Phase 3+ (£80–150/mo)**: upgrade Hetzner, add managed Postgres, apply for AWS Activate credits for backtest bursts
- **Never**: home internet as execution path, LD4 colocation (not worth it at this bankroll)

AWS is acceptable but **not** for always-on execution — too expensive relative to Hetzner. Use AWS for backtest spot instances and S3 for the 1.5TB Betfair historical archive when we need it.

## Error Handling & Failure Modes

- **Redis down** → services retry with exponential backoff; if market-data gap >5s, strategies auto-pause and emit a risk.alert
- **Exchange API down** → Execution Engine rejects; Risk Manager logs; dashboard alerts
- **Simulator diverges from live** → nightly reconciliation job compares paper fills against what would have filled given the tick data; alert if CLV divergence >2%
- **Kill switch** → dashboard button flips a flag in Redis; Risk Manager refuses all orders until cleared
- **Agent runaway spending Claude tokens** → the Orchestrator has a daily token budget configured in env; exceeds → pauses

## Testing Strategy

- Unit tests for strategy logic (pure functions — easy)
- Integration tests with a mocked Redis and mocked exchanges
- **Canary backtests**: every new strategy must pass against a known-good baseline strategy (e.g. "always back favourites") — flag if it's worse
- Smoke test on Hetzner VPS before any Betfair live credential is loaded
- Never test against Betfair live with real money except via the approved strategy path

## Implementation Order

1. **Scaffolding + CI** — repo, lint, CI, Docker Compose for local dev
2. **Ingestion service** (Betfair first — Kalshi second)
3. **TimescaleDB** with historical data backfill
4. **Simulator** (enough to feed one dummy strategy)
5. **Strategy Registry + one hand-coded toy strategy** running in simulator end-to-end
6. **Dashboard v0** — can see the toy strategy's paper P&L
7. **Risk Manager**
8. **Research Orchestrator v0** — Claude + wiki reads + generates hypothesis + runs backtest
9. **Wiki Maintenance Agent** — ingest/query/lint modes
10. **Execution Engine (Rust)** — only after paper side is proven
11. **Apply for Betfair live app-key**
12. **First human-approved paper-promoted strategy → live** (≤£100 stake, lowest risk)

## Non-Goals (Phase 0–1)

- Polymarket integration (deferred — UK geoblock, crypto CGT)
- Sub-millisecond latency (Betfair's own 40–100ms floor makes this a red herring at this scale)
- LD4 colocation
- GPU training (Hetzner/Oracle CPU is enough until we have a strategy worth accelerating)
- Mobile dashboard (desktop web is fine)

## Open Questions

1. Exact Betfair app-key approval process in 2026 — is live access fast, or delayed?
2. Kalshi ToS stance on UK residents routing via Chicago VPS — need to ask support
3. Do we want Git-version-control the wiki (commit per ingestion) or a daily snapshot?
4. Should the research orchestrator run continuously or cron-triggered? (Cost vs freshness trade-off.)
5. Which exact CLV/Sharpe/drawdown thresholds count as "promote to paper"? Needs to be a concrete numeric gate before we can build the orchestrator.

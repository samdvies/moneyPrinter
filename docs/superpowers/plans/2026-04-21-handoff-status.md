# Handoff — Status & Next Steps (2026-04-21)

> **Purpose:** brief a fresh Claude instance on where the project is, what just landed, which decisions are open, and what to pick up next. Read CLAUDE.md and `docs/superpowers/plans/2026-04-20-phase6-7-roadmap.md` alongside this.

## Where we are

- **Branch:** `main` at `16e6477` (merge commit of `phase6-edge-generation`). Remote is `origin` → `github.com/samdvies/moneyPrinter.git`. Both pushed.
- **Phases 1 → 6b are complete** on `main`. Last merge brought ~5k lines across 55 files: backtest harness, market-data archive, mean-reversion reference strategy, wiki↔registry loader, wiki write-back.
- **Test state:** green. Orchestrator 12, strategy-registry 65, backtest-engine tests all passing. `uv run ruff check` + `mypy` clean (one pre-existing UP047 in `risk_manager/tests` that predates this branch — untouched).
- **Uncommitted tracked changes on `main`** from the LLM-provider rename (kept local pending user commit):
  - `.env.example` — added `XAI_API_KEY` + `XAI_MODEL` block
  - `CLAUDE.md` — "Claude API" → "xAI Grok API, OpenAI-compatible"
  - `docs/superpowers/specs/2026-04-18-algo-betting-design.md` — section heading updated
  - `services/research_orchestrator/src/research_orchestrator/workflow.py:41` — stub docstring
- **Untracked new docs on `main`:**
  - `wiki/20-Markets/Venue-Strategy.md` — venue-tier decision (Smarkets T1, Betfair Live T4 £499 deferred)
  - Several earlier plan docs + devil's-advocate docs that were already untracked before 6b merged (pre-existing; not this session).

## Recent pivots (read these before planning 6c or 7a)

1. **LLM provider → xAI Grok** (not Anthropic Claude). OpenAI-compatible SDK; base_url `https://api.x.ai/v1`; env var `XAI_API_KEY`; default model `grok-4-fast-reasoning`. No prompt caching available. See `memory/project_llm_provider.md`.
2. **Primary venue → Smarkets** (not Betfair). Triggered by Betfair's **£499 one-off Live App Key fee**. Smarkets has a free real-time API with live orders and adequate UK sports liquidity. Betfair Delayed (free, snapshot data) is Tier 2; Betfair Live (£499) is Tier 4, purchased post-paper-validation. Matchbook (Tier 3) deferred; Betdaq skipped. Full rationale in `wiki/20-Markets/Venue-Strategy.md`.
3. **Kalshi dropped, ForecastEx slotted in** (2026-04-21). Kalshi's 23 October 2025 Member Agreement lists the UK as a Restricted Jurisdiction — Phase 7c as originally written ("Kalshi parity") is not executable for a UK resident. Replaced with ForecastEx (Interactive Brokers, CFTC-regulated, UK-accessible via IB; market scope: US macro + politics + climate). The `services/ingestion/src/ingestion/kalshi_adapter.py` scaffold stays in-tree as reference only; no further Kalshi engineering. See `wiki/20-Markets/Venue-Strategy.md`.
4. **Polymarket re-eval 2026-04-21.** LLM-pitched "maker-rebates + graduated-KYC + unified SDK" angle reviewed and rejected. UK IP geoblock fires before any KYC tier, so the under-threshold-hobbyist path is not available. Decision: deferred, benched as ideas backlog. Canonical rebuttal with sources in `wiki/20-Markets/Polymarket-Feasibility-2026.md`.

## Latency Posture

The stack already allocates latency where it matters; this section exists so a fresh instance doesn't misread recent pivots as an abandonment of the latency story.

- **Research loop (6c Grok)** — slow by design. Hypothesis generation does not need sub-second round trips.
- **Execution hot path (Phase 7 Rust)** — fast by design. The `execution/` crate is Rust specifically to avoid Python GIL jitter on place-order round trips.
- **Reference strategy (6b mean-reversion)** — tick-driven. Needs Smarkets real-time feed; Betfair Delayed (1-180s snapshots) would starve it.

**Strategy selection for a low-capital bot with good-hobbyist-tier latency (10-50ms from a UK VPS near Smarkets):** beats retail and slow-bots on Smarkets / Betfair Exchange-adjacent books; loses every race to colocated HFT. Favour edges where HFT doesn't play — thinner UK sports markets, retail-emotion-driven moves, structural mispricings that take >500ms to close (Matchbook↔Smarkets divergences), slow-horizon mean-reversion. Deprioritise strategies that die inside 50ms.

## Next phases

Per the roadmap (`2026-04-20-phase6-7-roadmap.md`), 6b unblocks **6c and 7a in parallel**:

- **6c — Agentic hypothesis generation.** Replace `workflow.hypothesize()` stub with an xAI Grok call that emits a wiki strategy spec + Python module. Safety invariant: AST walker on strategy modules (pure `(snapshot, params) → signal | None`). Plan doc not yet written.
- **7a — Rust execution scaffold.** First primitives crate. **Now targeting Smarkets first**, not Betfair — venue pivot supersedes the original roadmap wording. Plan doc not yet written.

Recommended order: **write the 6c plan first, then 7a.** 6c compounds on the harness + reference strategy just landed; 7a is blocked on live Smarkets credentials the user may not yet hold.

## Open decisions (flagged — do NOT resolve silently)

### D1 — Commit the in-flight rename?
The LLM-provider rename is uncommitted on `main`. Do NOT auto-commit. Ask the user whether to bundle it with the venue-strategy wiki doc in one "docs: pivot to Grok + Smarkets" commit, or keep them separate.

### D2 — Default Grok model for 6c
`grok-4-fast-reasoning` was picked as the default in `.env.example` (latency-oriented reasoning model). Could also be `grok-4` (higher quality, higher cost/latency) or `grok-4-fast-non-reasoning` (cheapest). Commit in the 6c plan after estimating per-hypothesis token budget. Open.

### D3 — Prompt strategy for 6c without caching
xAI has no prompt-cache primitive. Either (a) send a minimal rotating system prompt per hypothesis, or (b) batch-generate N hypotheses per call to amortise the fixed preamble. Open; resolve during 6c brainstorming.

### D4 — Phase 7a venue rewrite scope
The roadmap's 7a naming was `execution-betfair` first. Venue pivot now says `execution-smarkets` first. Two ways to execute:
- (a) Edit the roadmap doc in-place (it's an untracked working-copy doc; churn cost low),
- (b) Write the 7a plan doc referencing the venue pivot and let the roadmap drift until a natural cleanup pass.
Open. Prefer (a) before 7a begins; otherwise two sources of truth.

### D5 — Matchbook / Betdaq inclusion
Decision saved: Matchbook deferred, Betdaq skipped. User floated including them "for learning." Final direction is Smarkets-only-first. If user pushes back later, Matchbook Tier 3 stays the correct promotion path. Do not add these proactively.

### D7 — Kalshi UK access (RESOLVED 2026-04-21)
Resolved: **replace Kalshi with ForecastEx** in the roadmap. Kalshi's Member Agreement (23 Oct 2025) lists the UK as a Restricted Jurisdiction — no "Kalshi Global" carve-out unlocks UK residency. Phase 7c rewritten to target ForecastEx via Interactive Brokers (CFTC-regulated, UK-accessible). Existing `kalshi_adapter.py` remains as reference; no further Kalshi engineering until a non-UK entity exists. Polymarket stays deferred per the same review.

### D6 — Credentials the user needs to provision before 7a
- `XAI_API_KEY` — **required for 6c**, not 7a.
- Smarkets: username/password + API URL (demo vs prod) — **required for 7a** once plan is ready. Free, no activation fee.
- Betfair Delayed App Key — **required for Tier 2 ingestion work**. Free; personal-use signup.
- Betfair Live App Key (£499) — **deferred**, not needed until a strategy is paper-validated.
- Kalshi demo API key — needed when Phase 2b Kalshi ingestion is revisited (not blocking 6c/7a).
Open question for the user: which of these do they hold today? The handoff should prompt them to answer.

## What a fresh instance should do first

1. `git status` + `git log --oneline -5` to confirm `main` is at `16e6477` with four uncommitted tracked files from the Grok rename.
2. Read `memory/MEMORY.md`, `CLAUDE.md`, this doc, `docs/superpowers/plans/2026-04-20-phase6-7-roadmap.md`, `wiki/20-Markets/Venue-Strategy.md` — in that order.
3. Ask the user: "Commit the Grok rename? Provision credentials? Begin 6c planning, 7a planning, or both?" — do not pick silently.
4. Use `superpowers:brainstorming` before `superpowers:writing-plans` for 6c (the provider shift + no-cache constraint changes the design shape from a pre-pivot plan).

## File pointers for a fresh instance

- `CLAUDE.md` — project invariants (human gate, £1k cap, UK-legal venues).
- `docs/superpowers/plans/2026-04-20-phase6-7-roadmap.md` — Phase 6/7 decomposition. **Caveat:** still names Betfair as primary execution venue in places; venue pivot supersedes.
- `docs/superpowers/plans/2026-04-20-phase6b-reference-strategy.md` — last shipped plan; good template for 6c/7a shape.
- `wiki/20-Markets/Venue-Strategy.md` — authoritative venue tiering.
- `wiki/20-Risk/open-debts.md` — residual debts list; check before closing items.
- `services/research_orchestrator/src/research_orchestrator/workflow.py` — the stub `hypothesize()` 6c replaces.
- `memory/MEMORY.md` — all project memory entries; read all before planning.

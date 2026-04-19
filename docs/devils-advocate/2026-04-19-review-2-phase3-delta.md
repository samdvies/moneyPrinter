---
title: Devil's Advocate Review #2 — Phase 3 Delta
type: review
date: 2026-04-19
reviewer: devils-advocate (general-purpose dispatch)
prior-review: ~/.claude/plans/i-want-you-to-swirling-meerkat.md
branch-at-review: cursor/phase3-simulator-and-registry
status: open
---

# Devil's Advocate Review #2 — algo-betting (Phase 3 Delta)

## 1. Top concerns (ranked)

1. **The hard-coded promotion gate exists in software but the numerics it gates on still don't.** The state machine is correct; what enters it isn't defined.
2. **Simulator's fill model will systematically over-state P&L.** No latency, no queue position, no Betfair bet-delay, no maker/taker fees — published evidence puts this delta at 20–50%+.
3. **Kalshi UK legality is documented as a CRITICAL blocker in `wiki/20-Markets/Viability-Reality-Check.md` but `CLAUDE.md` and Phase 2b plan still treat Kalshi as in-scope.** The team wrote the answer down and didn't act on it.
4. **Service ordering is wrong for the stated bottleneck.** Five execution-plumbing phases shipped; zero strategies, zero foundations, zero competitor model.
5. **`paper API ≡ live API` invariant is leaky at the simulator boundary.** Strategies will be able to detect they're in sim from the response distribution.
6. **Registry has no `live` exposure cap, no kill-switch hook, no portfolio-level state.** The £1k cap from `CLAUDE.md` is unenforced anywhere in code.
7. **`approved_by` is a free-form string with no auth.** Any process with DB write can self-promote a strategy to live.

---

## 2. Severity 1 — could invalidate the project

### 1.1 Promotion gate is plumbing without numbers

`services/strategy_registry/src/strategy_registry/transitions.py:13-20` correctly enforces `awaiting-approval → live` only with a non-empty `approved_by`. That is the *easy* half of the gate. The hard half — what evidence justifies clicking the button — is still undefined. The Phase 3b plan (`docs/superpowers/plans/2026-04-19-phase3b-strategy-registry.md:12`) explicitly punts: *"automatic promotion based on metrics (Phase 4)"*. Task B6 in `docs/superpowers/plans/2026-04-18-obsidian-mcp-and-research.md:262` is **still unchecked**.

Net: a beautifully audited state machine gates a transition the operator has no objective basis to make. Without numeric thresholds, the human gate is theatre — the operator will approve based on vibes and recency. This was Severity 1 in the prior review and **nothing concrete moved on it**. Resolve before Phase 4 orchestrator work.

### 1.2 Kalshi UK status: documented blocker, unacted

`wiki/20-Markets/Viability-Reality-Check.md:160-172` now states plainly: *"Trading Kalshi from the UK as a UK resident is unlicensed gambling under UK law."* Yet `CLAUDE.md:11` still reads *"UK legal scope only — Betfair + Kalshi"* and `docs/superpowers/plans/2026-04-19-phase2b-kalshi-ingestion.md` ships. Task B5 (the legal go/no-go research) is still unchecked.

This is a discipline failure as much as a strategy one: the team did the research, wrote down the answer, and then continued building toward the venue anyway. Either (a) explicitly reframe Kalshi as research/data-only in `CLAUDE.md` and remove it from the Execution Engine roadmap, or (b) replace it with Smarkets / Matchbook. Sources: [UKGC position via OddsPedia](https://oddspedia.com/insights/betting/where-is-kalshi-legal); [Kalshi help — international eligibility](https://help.kalshi.com/en/articles/14026044-can-i-trade-on-kalshi-from-outside-the-united-states).

### 1.3 Simulator P&L will not survive contact with live exchange microstructure

`services/simulator/src/simulator/fills.py:1-9` is candid: *"No randomness, no latency modelling. Fills are crossed against the best available price levels."* Specifically missing:

- **No queue position model.** Limit orders cross instantly if the top-of-book price matches; in reality a limit order joins the back of the queue at that price and may never fill. This is the single biggest source of paper-vs-live divergence in maker strategies.
- **No latency/delay.** Order matched against the same `MarketData` snapshot it was emitted from. In live trading the book has moved by the time the order arrives — that's adverse selection.
- **No Betfair bet-delay.** Per [Betfair developer support](https://support.developer.betfair.com/hc/en-us/articles/360002825652-Why-do-you-have-a-delay-on-placing-bets-on-a-market-that-is-in-play), in-play orders are delayed 1–8 seconds (1s for horse racing in-play). Any in-play simulator P&L without this is fiction.
- **No fees.** No 5% Betfair commission, no Expert Fee tier, no Kalshi `roundup(0.07·C·P·(1-P))` non-linearity. A backtest with this fill engine will show edges that don't exist post-fee.
- **No partial-fill timing.** `_walk_ladder` (`fills.py:33-62`) consumes multiple levels in one tick — in live trading this would be a sequence of fills with the book reacting between each.

Published evidence: 20–50% performance reduction is *typical* for a backtest→live transition, *largest for short-horizon strategies* ([HackerNoon: Why Your Backtest Fails Live](https://hackernoon.com/why-your-profitable-backtest-fails-the-moment-you-go-live), [LuxAlgo backtesting limitations](https://www.luxalgo.com/blog/backtesting-limitations-slippage-and-liquidity-explained/)). The Phase 3a plan acknowledges these as "extensions" (`2026-04-19-phase3a-simulator-service.md:111`) — they are not extensions, they *are* the model. Without them the simulator does not perform its stated job: deciding whether a strategy deserves real capital.

**Concrete consequence:** if you advance any strategy from paper → awaiting-approval based on this simulator's P&L, you will be approving an instrument that is structurally over-fitted to a frictionless world.

---

## 3. Severity 2 — materially shrinks expected returns

### 2.1 `paper API ≡ live API` invariant has a leak the strategy can sniff

`services/simulator/src/simulator/engine.py:32-42` returns `status="placed"` with a freshly-minted UUID *immediately* on signal receipt when no book snapshot exists, and `services/simulator/src/simulator/fills.py:88-96` returns the `ExecutionResult` synchronously with `timestamp=datetime.now(UTC)`. In live, the venue assigns the order ID, fill latency is non-zero and variable, and resting orders have a real exchange-side state.

A strategy can detect simulator mode via:
- Response time distribution (sim is sub-ms, live is 20–200ms).
- Order-ID format (simulator uses Python uuid4; Betfair returns its own bet IDs, Kalshi its own).
- Absence of partial-fill streams (sim returns one terminal `ExecutionResult`; live returns a sequence).

This violates the project's stated core invariant (`CLAUDE.md`: *"Strategies must not know if they are in sim or live"*). Either the schema should hide this (force the venue adapter to mint IDs in the same format) or the invariant should be downgraded to "the *interface* matches; the *distribution* does not".

### 2.2 Registry encodes lifecycle but not capital exposure

`services/strategy_registry/src/strategy_registry/models.py:32-42` has no `max_exposure_gbp`, `max_position_size`, or per-venue limit fields. `CLAUDE.md` mandates a £1,000 cap; that cap exists nowhere in code. The `transition()` function (`crud.py:109-176`) lets a strategy enter `live` with no associated risk parameters. Phase 3c (risk manager) will need to read these values from somewhere — currently nowhere.

### 2.3 `approved_by` has no authentication

`crud.py:144-159` writes whatever string the caller passes. Any process with DB credentials (CI runner, ad-hoc script, agent with broad tool access) can call `transition(strategy_id, "live", approved_by="me")` and bypass the human entirely. Documented as a deferred concern (`README` per plan §Open Dependencies) but this is the *only* enforcement layer between research and real money — deferring it is the wrong call. At minimum require approval to come from a signed file or env var the agent cannot write.

### 2.4 `record_fill` updates `status` from a downstream non-authoritative writer

`services/simulator/src/simulator/persistence.py:94-115` updates `orders.status` directly. The promotion-gate spec (`docs/superpowers/plans/2026-04-19-phase3b-strategy-registry.md:15`) says *"no module may UPDATE strategies SET status= directly"* — but `orders.status` is not gated by the same discipline and will be the actual signal the dashboard uses to compute paper P&L. Drift between fill source-of-truth and registry is now possible.

---

## 4. Severity 3 — process / discipline gaps

### 3.1 Foundations directory is still empty of domain content

`wiki/10-Foundations/` contains only `Karpathy-LLM-Wiki.md`. No CLV note, no Kelly note, no microstructure note, no competitor model. The prior review flagged this; nothing changed. Without these, every "edge" claim made by the future orchestrator is unfalsifiable.

### 3.2 Build-order continues to favour plumbing over strategy

Since the prior review the team shipped: simulator (six tasks), registry (five tasks), Kalshi adapter scaffold, ingestion polish. Strategy artifacts shipped in the same period: **zero** — `wiki/30-Strategies/` is empty (template only). The execution-side architecture is now ~75% built and there is still nothing for it to execute. The "you can't do strategy work without paper-trading rails" defence is partly fair but: a single Jupyter notebook backtesting a closing-line-value strategy on Betfair Historical Data would teach more about whether this project can make money than the entire Phase 3 work just shipped.

### 3.3 Plan documents continue to track tasks, not hypotheses

Each phase plan defines what to build but never *what we'd see that would invalidate the project*. A plan should include a "kill conditions" section: e.g., "if no strategy clears CLV>1% on Betfair pre-race after 90 days of orchestrator runs, retire the orchestrator". Without this, sunk-cost bias compounds.

### 3.4 No promotion-gate-auditor evidence in the diff

`2026-04-19-phase3b-strategy-registry.md:84` checkbox claims auditor was invoked. No artefact in the repo records the audit findings. Treat checkbox as unverified.

---

## 5. Delta from prior review

| Prior concern | Status |
|---|---|
| Kalshi UK legal status | Researched (`Viability-Reality-Check.md`), **not acted on** in `CLAUDE.md` or plans |
| Numeric promotion thresholds | Task scheduled (B6), **still unchecked**; state machine built around the void |
| Fee math end-to-end | Documented in wiki, **not in simulator** |
| Competitor model | Single paragraph in viability doc; no per-strategy field |
| Pick a strategy lane | Not done — no strategies exist |
| Capital floor math | Not done |
| Foundations notes | Not done |

Summary: research deliverables landed in the wiki, engineering deliverables in `services/`. The two streams have not crossed. The wiki tells you Kalshi is blocked; the plans schedule more Kalshi work. The wiki tells you fees swallow most edges; the simulator models zero fees.

---

## 6. Calibration — what's genuinely working

- **State machine design is correct and minimal.** Pure `transitions.py` separated from DB-touching `crud.py` is the right factoring. SELECT FOR UPDATE re-validation under lock (`crud.py:132-142`) is the textbook TOCTOU guard. This module would survive a security review.
- **Atomic approval columns.** `crud.py:145-159` sets `approved_by` + `approved_at` in the same UPDATE as `status='live'`. Cannot be split.
- **Simulator's live-mode rejection is belt-and-braces correct.** `engine.py:67-80` emits a critical `RiskAlert` and drops the signal. Even if the risk manager fails open later, this stops accidental live routing.
- **Stale-tick rejection in the book** (`book.py:19-21`) prevents replay-induced phantom fills.
- **Schema discipline holds.** `OrderSignal` and `ExecutionResult` (`services/common/src/algobet_common/schemas.py:41-58`) remain unchanged across the new code — strategies see one shape only.
- **Viability research is excellent.** `Viability-Reality-Check.md` is one of the best devil's-advocate documents in this kind of hobbyist trading repo. The problem is acting on it, not producing it.

---

## 7. Concrete research-only recommendations

1. **Update `CLAUDE.md` today.** Reframe Kalshi as research/data-only with no live execution path, and add an item: "Severity-1 invariants from `wiki/20-Markets/Viability-Reality-Check.md` are binding on plan documents." This costs nothing and stops Kalshi engineering drift.
2. **Write `wiki/30-Strategies/Promotion-Thresholds.md` before Phase 4.** Numeric floor for: backtest N (e.g. ≥1000 trades), out-of-sample holdout (≥30%), walk-forward windows, Sharpe floor (e.g. >1.5), max drawdown ceiling, paper trading minimum (≥6 weeks AND ≥500 trades), CLV margin floor (>1%), multiple-testing correction policy (Bonferroni or BH-FDR), edge-decay retirement rule. Cite Buchdahl + Pinnacle + López de Prado.
3. **Before Phase 4, add a "fee + slippage + latency" pass to the simulator plan.** Specifically: configurable per-venue commission, Betfair bet-delay, Kalshi non-linear fee, queue-position probability model (simplest viable: random fill probability ≤ size_at_price / total_at_price), and a Gaussian latency draw on order arrival. Otherwise the orchestrator's outputs are unreliable.
4. **Add `max_exposure_gbp` and `risk_params` JSONB columns to `strategies` in a 0003 migration.** Make `transition→live` validate they exist and are within global caps. Without this the £1,000 invariant is uncodified.
5. **Tighten `approved_by`.** Require it to match a value in an allowlist file (or a signed token). Document that DB-write access ≠ approval authority.
6. **Pick the first strategy and write the note.** A pre-race CLV-tracking Betfair horse racing strategy with explicit competitor-model paragraph (Starlizard, Smartodds, Bet365, retail squares — for each, *why is your edge over them plausible?*). If that paragraph is hard to write, the project's central premise is the bottleneck, not the engineering.
7. **Add a "kill conditions" template to `wiki/90-Templates/`** and apply it retroactively to phase plans.

---

## 8. Sources

- [Betfair developer — in-play bet delay](https://support.developer.betfair.com/hc/en-us/articles/360002825652-Why-do-you-have-a-delay-on-placing-bets-on-a-market-that-is-in-play)
- [HackerNoon — Why Your Profitable Backtest Fails Live](https://hackernoon.com/why-your-profitable-backtest-fails-the-moment-you-go-live)
- [LuxAlgo — Backtesting Limitations: Slippage and Liquidity](https://www.luxalgo.com/blog/backtesting-limitations-slippage-and-liquidity-explained/)
- [PineConnector — Backtesting vs Live Trading](https://www.pineconnector.com/blogs/pico-blog/backtesting-vs-live-trading-bridging-the-gap-between-strategy-and-reality)
- [OddsPedia — Where is Kalshi Legal](https://oddspedia.com/insights/betting/where-is-kalshi-legal)
- [Kalshi Help — international eligibility](https://help.kalshi.com/en/articles/14026044-can-i-trade-on-kalshi-from-outside-the-united-states)
- [Kalshi Fee Schedule](https://kalshi.com/fee-schedule)
- [Bürgi, Deng & Whelan 2025 — Kalshi taker losses (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5502658)
- [arXiv 2402.02623 — Betfair UK horse racing efficiency](https://arxiv.org/abs/2402.02623)
- [Bet Angel — Betfair trading on a VPS](https://www.betangel.com/betfair-trading-on-a-vps/)

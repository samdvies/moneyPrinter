---
title: "Venue Strategy — UK Sports Exchange Access"
type: decision
tags: [venue, betfair, smarkets, matchbook, betdaq, api-pricing, decision]
status: active
created: 2026-04-21
updated: 2026-04-21
---

# Venue Strategy — UK Sports Exchange Access

## Decision (2026-04-21)

Shift primary venue from Betfair to **Smarkets** for the research and paper-trading phases. Betfair access is retained but delayed until a proven strategy justifies the £499 Live App Key. Other UK exchanges (Matchbook, Betdaq) are deferred unless a concrete use-case (e.g. cross-venue arbitrage) promotes them.

## Update (2026-04-21, same day)

- **Kalshi dropped, ForecastEx slotted in.** Kalshi's 23 October 2025 Member Agreement lists the UK as a Restricted Jurisdiction; no "Kalshi Global" carve-out unlocks UK residency. The original roadmap's Phase 7c Kalshi-parity target is not executable for a UK-resident operator. ForecastEx (via Interactive Brokers) replaces Kalshi as the second non-sports venue candidate — CFTC-regulated, UK-accessible through IB, narrow scope (US macro + politics + climate). The `services/ingestion/src/ingestion/kalshi_adapter.py` scaffold stays in-tree as reference only.
- **Polymarket re-evaluation.** The 2026 "maker-rebate + graduated-KYC + unified SDK" pitch was fact-checked. The UK IP geoblock fires before any KYC tier (not the other way around), so the "trade small under the threshold" path is unavailable to a UK-resident operator. Decision: deferred, benched as ideas backlog, not revisited without a legal-structure change. Full rebuttal in [[Polymarket-Feasibility-2026]].

## Latency budget

The reference strategy (6b mean-reversion on best-bid/ask mid-price) is **tick-driven**. It requires Smarkets' real-time feed; Betfair Delayed's 1-180s snapshots would starve the rolling-window calculation. This is the reason Smarkets is T1, not just a preference — the data-freshness axis is load-bearing.

Hobbyist-tier network latency (UK VPS → Smarkets, ~10-50ms round trip) beats retail and lazy bots on Smarkets and Betfair Exchange-adjacent books, but does not beat colocated HFT. Strategy selection should therefore favour edges where HFT does not play: thinner UK sports markets, retail-emotion-driven moves, structural mispricings that take >500ms to close (e.g. Matchbook↔Smarkets divergences), and slow-horizon mean-reversion. Strategies that die inside 50ms are out of scope for this project regardless of venue.

## Context — What prompted the shift

Original architecture named Betfair + Kalshi as the two venues. On a pricing review it became clear Betfair's real-time Exchange API requires a **£499 one-off activation fee** for a Live App Key (personal-betting tier, non-refundable, debited directly from the Betfair account balance). Paying £499 up front for a venue before any strategy has cleared paper trading inverts the project's "prove it first" risk invariant — we wouldn't deploy £1,000 in capital on an unproven strategy, so we shouldn't buy a £499 data key for the same.

A free Betfair **Delayed App Key** does exist (personal use, real orders allowed, but market data is 1–180s snapshots with only 3 price levels and no traded volume / BSP). That kills latency-sensitive strategies but is viable for slow-horizon research.

Meanwhile **Smarkets** publishes a free real-time API with live order placement and decent UK sports liquidity (football, horses). It is the lowest-friction legitimate route to live-money exchange trading in the UK.

## Tiering

| Tier | Venue | Cost | Data | Orders | When to build |
|---|---|---|---|---|---|
| 1 | **Smarkets** | Free | Real-time | Live | **Now** — primary research + paper + live venue |
| 2 | **Betfair Delayed** | Free | 1–180s snapshots, 3 levels, no BSP | Live (allowed with delayed key) | Shortly after T1 — slow-horizon strategies only, also a stepping stone to T4 |
| 3 | **ForecastEx** (via Interactive Brokers) | Free; IB account; CFTC-regulated | Real-time | Live | **Deferred candidate** — second venue slot replacing Kalshi. Add after a Smarkets-validated strategy exists AND a concrete US-macro / politics / climate hypothesis surfaces |
| 3 | **Matchbook** | Free <1M GET/mo | Real-time | Live | **Deferred** — add only if a cross-venue arbitrage hypothesis justifies the adapter cost |
| 4 | **Betfair Live** | **£499 one-off** | Full ladder, real-time, BSP, traded volume | Live | **Deferred** — purchase only once a Smarkets-validated strategy has cleared paper trading and the human approval gate |
| — | Kalshi | Free account, US residency required | Real-time | Live | **Out of scope for UK resident** — Member Agreement 23 Oct 2025 lists UK as Restricted Jurisdiction. Scaffold in `kalshi_adapter.py` stays as reference only |
| — | Betdaq | Free | Thin liquidity | Live | **Skipped** — learning value marginal, liquidity too thin for research; adapter cost not recouped |
| — | Polymarket | — | — | — | **Deferred / benched** — UK IP geoblock fires before any KYC tier, under-threshold path unavailable. See [[Polymarket-Feasibility-2026]] |
| — | Limitless | — | — | — | **Not evaluated** — DeFi protocol on Base; UK legal status unverified; crypto CGT overhead would apply |

## Rationale for not building every "free" adapter

Each additional venue costs ~1 engineering-week of adapter, auth, market-ID mapping, test fixtures, and routing in `order.signals`. Three "for learning" adapters is three weeks of plumbing that do not move the project closer to edge. A single well-abstracted adapter (Smarkets) with clean venue boundaries makes Tier 2–4 fill-in-the-blanks later. Reuse, not repetition.

If the goal is *practice* at writing venue adapters, Matchbook gives that lesson at better liquidity than Betdaq and on a production-relevant venue. Betdaq does not clear that bar.

## Engineering implications

- **Phase 2 (ingestion):** add `services/ingestion/src/ingestion/smarkets_adapter.py`. `betfair_adapter.py` stays in the tree but defaults to the Delayed App Key in dev. Kalshi adapter (scaffolded) remains on its roadmap track; it targets US event contracts, not UK sports.
- **Phase 7 (execution, Rust):** first crate is `execution-smarkets`, not `execution-betfair`. The Cargo workspace keeps `execution-betfair` reserved in the members list but the 7a plan lands Smarkets first. `execution-betfair-live` waits until the £499 key is purchased.
- **Env vars:** add `SMARKETS_USERNAME`, `SMARKETS_PASSWORD`, `SMARKETS_API_URL` (demo vs prod) to `.env.example` during Phase 2 rewire. Betfair env vars stay, retargeted to the Delayed key.
- **Orchestrator:** `strategies.venue` already permits `smarkets` via a schema extension — confirm in the migration when Smarkets lands.

## When to revisit

- **Buy the £499 Betfair Live key when:** one or more Smarkets-validated strategies have cleared ≥ 2 weeks of paper trading AND the human approval gate AND the Betfair market-structure edge (deeper ladder, BSP) is material to the strategy's expected value. Budget the £499 against the strategy's paper-trade-realised edge, not as sunk R&D cost.
- **Add Matchbook when:** a specific cross-venue arbitrage hypothesis emerges (Smarkets vs Matchbook price divergence on the same market). Not before.
- **Reconsider Betdaq** only if a Ladbrokes-group-specific edge hypothesis emerges — considered unlikely.
- **Add ForecastEx when:** a concrete hypothesis surfaces in its scope (US macro indicators, US politics, climate contracts). Requires an Interactive Brokers account. Adapter cost ≈ one engineering week; IB API documentation is solid.
- **Revisit Kalshi** only if the user establishes a non-UK entity or changes residency. Otherwise the Member Agreement blocks the account at signup.
- **Revisit Polymarket** only on a legal-structure change (non-UK residency) or UK licensing of the platform. Re-opening on pitch-strength alone is out of scope per `feedback_no_polymarket` memory.

## Sources

- Betfair Developer — API costs: https://support.developer.betfair.com/hc/en-us/articles/115003864531
- Betfair Developer — Application Keys (Delayed vs Live): https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687105/Application+Keys
- Smarkets API docs: https://docs.smarkets.com/
- Matchbook Developer pricing: https://developers.matchbook.com/docs/pricing

## Related

- `CLAUDE.md` — update venue list from "Betfair + Kalshi" to "Smarkets + Betfair Delayed; ForecastEx candidate; Betfair Live deferred; Kalshi out-of-scope-for-UK"
- `docs/superpowers/plans/2026-04-20-phase6-7-roadmap.md` — Phase 7a primary execution crate is `execution-smarkets`; Phase 7c target changed from `execution-kalshi` to `execution-forecastex`
- `wiki/20-Markets/Betfair-Research.md` — existing Betfair research still valid; venue ranking demoted to Tier 2/4
- [[Polymarket-Feasibility-2026]] — canonical fact-check for the Polymarket deferral

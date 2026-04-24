---
title: "Venue Strategy — UK Sports Exchange Access"
type: decision
tags: [venue, betfair, smarkets, matchbook, betdaq, api-pricing, decision]
status: active
created: 2026-04-21
updated: 2026-04-22
---

# Venue Strategy — UK Sports Exchange Access

## Update (2026-04-24) — Polymarket-only focus until reversed

The operator has chosen to narrow the project's attention to **Polymarket only** until further notice. All other venues in this document (Matchbook, Betfair, Smarkets, Kalshi, ForecastEx, Betdaq, Orbit Exchange, Pinnacle, Matchbook Predictions, etc.) are **deferred pending explicit user reversal** — no engineering work, scaffolding, or proposals for those venues should be started without a direct instruction.

The previous "Deferred / benched" Polymarket row has been superseded by the **T2 data-only (VPN-gated)** entry added 2026-04-23; that ingestion adapter is live on main. The operator has weighed and accepted the Polymarket-specific trade-offs (ToS §2.1.4 VPN use, UK IP geoblock, CGT treatment of crypto disposals, fund-freeze risk at withdrawal). These are *accepted* risks, not unresolved blockers — future agents should not re-raise them when asked to work on Polymarket.

The legacy tiering below is retained as historical context so the trade-off analysis stays legible; interpret every "primary" / "T1 build now" / "paper validate this on Matchbook" phrase as currently superseded by the Polymarket-only focus. Reverse only on an explicit user instruction.

## Decision (2026-04-21)

Shift primary venue from Betfair to **Smarkets** for the research and paper-trading phases. Betfair access is retained but delayed until a proven strategy justifies the £499 Live App Key. Other UK exchanges (Matchbook, Betdaq) are deferred unless a concrete use-case (e.g. cross-venue arbitrage) promotes them.

## Update (2026-04-22) — Matchbook promoted to free Tier 1; Betfair Delayed order-placement correction

Following an exhaustive venue survey (see [[Venue-Alternatives-2026-04]]), two further changes are recorded here:

1. **Matchbook promoted to free Tier 1 real-time venue.** With Smarkets carrying a £150 admin fee that inverts the "prove it first" invariant, Matchbook is the only UK betting exchange offering a free REST API, free order placement (WRITE requests not charged), and real-time data without a setup fee. Commission is identical to Smarkets (2% net-win). Matchbook is now the primary build target for the Phase 2 ingestion adapter and the Phase 7a execution crate. Smarkets remains in the deferred queue with an explicit trigger: build the Smarkets adapter once a Matchbook-validated strategy is demonstrably liquidity-constrained.

2. **Correction: Betfair Delayed App Key does NOT permit order placement.** The tiering table below previously stated the Delayed key allows "Live (orders allowed)". This is wrong. Betfair's own developer support documentation and developer forum confirm that `placeOrders` returns `ACCESS_DENIED` when called with a Delayed key. The Delayed key is strictly read-only for market data research and pipeline development. Any order execution — including BSP orders — requires the Live key (£499 one-off). The table has been corrected below.

## Update (2026-04-22) — Matchbook polling usability materially upgraded (deep-dive finding)

Second research pass (see [[Venue-Alternatives-2026-04-deep]]) clarifies Matchbook billing granularity and rate behaviour:

1. **Billing is per-HTTP-call, not per-runner.** The `GET /edge/rest/events?include-prices=true` endpoint returns all events with all markets, all runners, and all price ladders in a single HTTP response. One GET = one billing unit regardless of the number of runners returned. The prior estimate of "1 request per 2.6 seconds" assumed per-runner billing — this was overly conservative. With the efficient `GET /events?include-prices=true` polling pattern, 1M GETs/month ≈ 23 calls/second within an 8-hour active window.

2. **Rate limit ceiling is 700 Events requests/minute** (confirmed from the Fair Usage Policy). This is the binding constraint, not the monthly budget. At 1-second poll intervals during an 8-hour active window, monthly GET usage is approximately 864,000 — comfortably under the 1M free threshold. The 10-minute hard blocking period applies if the per-minute limit is exceeded; the adapter must include a rate governor with safety margin below 700 req/min.

3. **No streaming feed exists.** Confirmed by SDK source inspection: `matchbook-technology/matchbook-sdk` contains only `core` and `rest` modules. The `StreamObserver` pattern is a REST callback idiom, not a WebSocket or push transport. Polling `GET /events` is the only real-time data path.

4. **Signal horizon implication:** Strategies with 1–5 second signal horizons are feasible on Matchbook's polling feed when using the efficient `GET /events?include-prices=true` endpoint. The previous 5–30 second floor was based on per-runner polling assumptions and is now revised down to ~1–2 seconds.

## Update (2026-04-22) — Smarkets £150 admin fee

User reports Smarkets levies a **£150 admin fee** for API access. This is better than Betfair's £499 but still inverts the "prove it first" invariant — paying £150 for a venue before any strategy has cleared paper trading is the same class of mistake as buying the Betfair Live key up front. **Smarkets demoted from T1 to deferred**; revisit once a paper-validated strategy justifies the spend. Trigger mechanism (one-off vs recurring vs volume-gated) needs confirming from Smarkets before a buy decision.

Note: Multiple community sources describe the Smarkets API as "free" without mentioning the admin fee — this inconsistency has not been resolved from a primary source. Email `api@smarkets.com` before paying.

## Update (2026-04-21, same day)

- **Kalshi dropped, ForecastEx slotted in.** Kalshi's 23 October 2025 Member Agreement lists the UK as a Restricted Jurisdiction; no "Kalshi Global" carve-out unlocks UK residency. The original roadmap's Phase 7c Kalshi-parity target is not executable for a UK-resident operator. ForecastEx (via Interactive Brokers) replaces Kalshi as the second non-sports venue candidate — CFTC-regulated, UK-accessible through IB, narrow scope (US macro + politics + climate). The `services/ingestion/src/ingestion/kalshi_adapter.py` scaffold stays in-tree as reference only.
- **Polymarket re-evaluation.** The 2026 "maker-rebate + graduated-KYC + unified SDK" pitch was fact-checked. The UK IP geoblock fires before any KYC tier (not the other way around), so the "trade small under the threshold" path is unavailable to a UK-resident operator. Decision: deferred, benched as ideas backlog, not revisited without a legal-structure change. Full rebuttal in [[Polymarket-Feasibility-2026]].
- **Polymarket second re-examination (2026-04-22):** User requested re-opening of the Polymarket question. Second pass found no material change — geoblock enforcement has strengthened, FCA binary options ban argument is live, CGT overhead applies, fund-freeze risk at withdrawal is real. Verdict: STILL DEFERRED. See [[Venue-Alternatives-2026-04-deep]] section 3 for full reasoning.

## Latency budget

The reference strategy (6b mean-reversion on best-bid/ask mid-price) is **tick-driven**. With the revised Matchbook assessment: `GET /edge/rest/events?include-prices=true` polled at 1-second intervals delivers full-market price snapshots at near-real-time. This is workable for signal horizons of 1–5 seconds (revised down from the prior 5–30 second floor). Betfair Delayed's 1–180s snapshots would starve the rolling-window calculation.

Hobbyist-tier network latency (UK VPS → Matchbook, ~10–50ms round trip) beats retail and lazy bots on Matchbook and Betfair Exchange-adjacent books, but does not beat colocated HFT. Strategy selection should therefore favour edges where HFT does not play: thinner UK sports markets, retail-emotion-driven moves, structural mispricings that take >500ms to close, and slow-horizon mean-reversion. Strategies that die inside 50ms are out of scope for this project regardless of venue.

## Context — What prompted the shift

Original architecture named Betfair + Kalshi as the two venues. On a pricing review it became clear Betfair's real-time Exchange API requires a **£499 one-off activation fee** for a Live App Key (personal-betting tier, non-refundable, debited directly from the Betfair account balance). Paying £499 up front for a venue before any strategy has cleared paper trading inverts the project's "prove it first" risk invariant — we wouldn't deploy £1,000 in capital on an unproven strategy, so we shouldn't buy a £499 data key for the same.

A free Betfair **Delayed App Key** does exist (personal use, market data ingestion only — orders NOT permitted; see correction above). That kills latency-sensitive strategies and blocks any order placement, but the data feed is viable for slow-horizon research and pipeline development.

**Matchbook** offers a free REST API with real-time data polling and live order placement (no setup fee, no admin fee, WRITE requests not charged). It is the lowest-friction legitimate route to live-money exchange trading in the UK given the current constraint that no venue fee should be paid before a strategy clears paper trading.

## Tiering

| Tier | Venue | Cost | Data | Orders | When to build |
|---|---|---|---|---|---|
| 1 | **Matchbook** | Free <1M GET/mo; £100/1M after; orders free | REST polling via `GET /events?include-prices=true`; ~1s effective latency; full ladder; 700 Events req/min ceiling | Live (orders permitted via standard API) | **Now** — primary research + paper + live venue. Adapter: poll at 1s intervals during 8-hour active windows; rate governor required |
| 2 | **Betfair Delayed** | Free | 1–180s snapshots, 3 levels, no BSP, no volume | **Blocked — `placeOrders` returns ACCESS_DENIED with Delayed key** | Data-only research; pipeline dev; stepping stone to T4 |
| 3 | **ForecastEx** (via IB Ireland) | Free; IB account; CFTC-regulated; ~3.14% APY on collateral | Real-time via TWS API | Live (if UK eligible via IB Ireland — empirical confirmation needed) | **Deferred candidate** — open IB Ireland account and confirm eligibility; add when a concrete US-macro / climate hypothesis surfaces. Tax: CGT (not gambling winnings) |
| 3 | **Smarkets** | **£150 admin fee** (trigger type unconfirmed — email api@smarkets.com before paying) | Real-time stream; full ladder | Live | **Deferred** — pay only after a Matchbook-validated strategy is demonstrably liquidity-constrained |
| 4 | **Betfair Live** | **£499 one-off** | Full ladder, real-time stream, BSP, traded volume | Live | **Deferred** — purchase only after a paper-validated strategy clears the human approval gate AND the BSP/full-ladder edge is material |
| — | Betdaq | **£250 one-off** (unverified — confirm with Betdaq directly) | Real-time | Live | **Out of scope** — pay-gated AND thinnest book; inferior to Matchbook in every dimension |
| — | Kalshi | Free account, US residency required | Real-time | Live | **Out of scope for UK resident** — Member Agreement 23 Oct 2025 lists UK as Restricted Jurisdiction |
| 2 | **Polymarket (data-only, VPN-gated)** | Free (no auth on public reads) | Gamma REST `/markets` at 5s poll across all active markets; `bestBid`/`bestAsk`/`lastTradePrice` per CLOB token; depth unknown without CLOB `/book` fan-out | **Not wired** — order placement requires Polygon wallet + USDC + VPN + ToS §2.1.4 acceptance; deferred to a separate capital-approval plan | **Now** for research/data — `services/ingestion/src/ingestion/polymarket_adapter.py` gated on non-GB/US egress. Trading path deferred |
| — | Limitless | — | — | — | **Not evaluated** — DeFi protocol on Base; UK regulatory status unverified; crypto CGT overhead |
| — | Matchbook Predictions | B2B-gated; pricing unpublished | Real-time (Matchbook infrastructure) | Live (if retail access granted) | **Watch actively** — first UKGC-licensed prediction market in UK (Jan 2026); winnings tax-free; contact b2b@matchbook.com when ready |
| — | BetConnect | API key required (approval-gated) | Limited | Live | **Low priority** — niche use case; useful if strategies get limited elsewhere |
| — | Orbit Exchange | **No public API** | N/A | N/A | **Dead end** — white-label Betfair; API not extended; not automatable |
| — | Pinnacle | UK blocked; API closed Jul 2025 | N/A | N/A | **Out of scope** — two independent blockers |
| — | Binary options | FCA permanent ban since 2 Apr 2019 | N/A | N/A | **Out of scope** — legally prohibited for UK retail |

## Data Sources (Free Research Pipeline)

These are read-only / data-only sources used for backtesting and model development. No execution capability; listed separately from the execution venue tiers above.

| Source | Cost | Coverage | Granularity | Depth | Format |
|---|---|---|---|---|---|
| **Betfair BSP CSV** (`promo.betfair.com/betfairsp/prices`) | Free; no account needed | GB + Irish horse racing (win + place) | Settlement price only | May 2008 – present | CSV, daily |
| **Betfair Basic historical** (`historicdata.betfair.com`) | Free; Betfair account required | All Betfair Exchange sports | 1-minute LTP; no volume; no ladder | 2016 – present | Proprietary bz2; `betfairlightweight` parses |
| **Betfair Advanced historical** | Paid; login to see price (community reports ~£10–40/sport/month, unverified) | All Betfair Exchange sports | 1-second; top-3 ladder; volume | 2016 – present | Proprietary bz2 |
| **Betfair Pro historical** | Paid; higher than Advanced (unverified) | All Betfair Exchange sports | ~50ms; full ladder; volume | 2016 – present | Proprietary bz2 |
| **football-data.co.uk** | Free; no login | 25+ leagues; 15+ bookmakers incl. Betfair + Pinnacle | Match-level closing odds + results | 1990s – present (English leagues) | CSV per season |
| **pmxt Data Archive** (`archive.pmxt.dev`) | Free; no API key | Polymarket orderbooks (research only — trading deferred) | Hourly snapshots | 2026 (extent unconfirmed) | Parquet |
| **Polymarket Gamma API** (`docs.polymarket.com`) | Free (public read endpoint) | Polymarket markets | Per-market price history | Unknown depth | REST JSON |
| **The Odds API** (`the-odds-api.com`) | 500 credits/mo free; $30/mo 20K | Betfair confirmed; Matchbook/Smarkets unconfirmed | Real-time aggregated odds | Current only (no multi-year history in free tier) | REST |
| **OddsPapi** (`oddspapi.io`) | 250 req/mo free; paid tiers | 350+ books incl. Pinnacle and sharp books | Near-real-time | Limited in free tier | REST |

## Rationale for not building every "free" adapter

Each additional venue costs ~1 engineering-week of adapter, auth, market-ID mapping, test fixtures, and routing in `order.signals`. Three "for learning" adapters is three weeks of plumbing that do not move the project closer to edge. A single well-abstracted adapter (Matchbook) with clean venue boundaries makes Tier 3–4 fill-in-the-blanks later. Reuse, not repetition.

Betdaq is a worse version of Matchbook in every dimension that matters here (£250 fee vs free; thinner book; weaker docs). It does not warrant an adapter.

## Engineering implications

- **Phase 2 (ingestion):** add `services/ingestion/src/ingestion/matchbook_adapter.py` as the primary real-time venue. Core polling primitive: `GET /edge/rest/events?include-prices=true` at 1-second intervals during active windows. Include a rate governor capped at ≤650 Events req/min (safety margin below 700 limit). `betfair_adapter.py` stays in the tree defaulting to the Delayed App Key for data-only research. Kalshi adapter (scaffolded) remains as reference only.
- **Phase 7 (execution, Rust):** first crate is `execution-matchbook`, not `execution-smarkets`. The Cargo workspace should reserve `execution-smarkets` and `execution-betfair-live` as later members. `execution-betfair-live` waits until the £499 key is purchased after paper validation.
- **Env vars:** add `MATCHBOOK_USERNAME`, `MATCHBOOK_PASSWORD`, `MATCHBOOK_API_URL` to `.env.example` during Phase 2 rewire. Betfair env vars stay, retargeted to the Delayed key for data ingestion only.
- **Orchestrator:** `strategies.venue` schema extension should add `matchbook` as a valid venue value.
- **Betfair BSP data pipeline:** add a separate offline ingestion job to pull from `promo.betfair.com/betfairsp/prices` (daily CSV, no auth needed) for horse racing BSP backtesting.
- **football-data.co.uk pipeline:** add a one-time bulk download job for football closing odds / results CSV files. Free, no API key, no rate limit.

## When to revisit

- **Buy the £499 Betfair Live key when:** one or more Matchbook-validated strategies have cleared ≥ 2 weeks of paper trading AND the human approval gate AND the Betfair market-structure edge (deeper ladder, BSP, traded volume) is material to the strategy's expected value.
- **Pay the £150 Smarkets fee when:** a Matchbook-validated strategy is demonstrably liquidity-constrained (measured slippage or unmatched orders in paper trading), not before. Confirm fee trigger and recurrence with Smarkets first.
- **Confirm ForecastEx eligibility when:** IB Ireland account opened; empirically check product availability. If confirmed, build the `ib_insync` adapter. Tax: CGT (not gambling winnings) — factor into net-edge calculation.
- **Add Matchbook Predictions when:** retail API access becomes available; pricing published. Contact `b2b@matchbook.com` to monitor.
- **Revisit Kalshi** only if the user establishes a non-UK entity or changes residency.
- **Polymarket trading path revisit** — read-only data is now live via `polymarket_adapter.py` after the 2026-04-23 empirical probe (see below). Trading still requires: (a) Polygon wallet with USDC, (b) acceptance of ToS §2.1.4 VPN-use risk, (c) CGT handling plan for per-trade disposal events, (d) fund-freeze risk plan at withdrawal. No trading until a separately-approved plan with explicit capital cap clears the human gate.

## Update (2026-04-23) — Polymarket promoted to data-only T2

Empirical probes from an NL ProtonVPN exit overturned the prior deferral for the **read-only** path:

- `scripts/polymarket_auth_probe.py` (W0): fresh Polygon EOA → `POST /auth/api-key` → HTTP 200 in 200 ms; full L2 credentials issued. No geoblock on the auth endpoint.
- `scripts/polymarket_order_probe.py` (W1): signed unfunded order → `POST /order` reached the server-side balance gate (`balance: 0, order amount: 50000`); geoblock did **not** fire before balance check. Trading path is reachable given USDC + allowances.
- Gamma `/markets`, CLOB `/book`, CLOB `/price` all return HTTP 200 with live data from NL egress; no credentials required.

The adapter at `services/ingestion/src/ingestion/polymarket_adapter.py` ingests all active markets from Gamma (public REST, 5s poll) and emits one `MarketData` message per CLOB `token_id`. The `Venue.POLYMARKET` enum entry and `market_id = token_id` convention deliberately leave the trading path uncontested: a future `execution_polymarket` service can consume `OrderSignal(venue=POLYMARKET, market_id=<token_id>, ...)` with no schema migration. Operator must run with Proton Free manual VPN toggle (NL) until deployment strategy moves to `gluetun` or a non-restricted VPS.

## Sources

- Betfair Developer — API costs: https://support.developer.betfair.com/hc/en-us/articles/115003864531
- Betfair Developer — Application Keys (Delayed vs Live): https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687105/Application+Keys
- Betfair Developer — When to use Delayed vs Live: https://support.developer.betfair.com/hc/en-us/articles/360009638032-When-should-I-use-the-Delayed-or-Live-Application-Key
- Betfair Developer Forum — placeOrders ACCESS_DENIED with Delayed key: https://forum.developer.betfair.com/forum/sports-exchange-api/exchange-api/3461-placeorders-access_denied-with-delayed-key
- Smarkets API docs: https://docs.smarkets.com/
- Matchbook Developer pricing: https://developers.matchbook.com/docs/pricing
- Matchbook Fair Usage Policy: https://developers.matchbook.com/docs/fair-usage-policy
- Matchbook Get Events endpoint: https://developers.matchbook.com/reference/get-events
- Matchbook SDK (core + REST modules, no WebSocket): https://github.com/matchbook-technology/matchbook-sdk
- Matchbook Developer getting started: https://developers.matchbook.com/docs/getting-started
- Betdaq API access (Zendesk — confirm £250 fee directly): https://betdaq.zendesk.com/hc/en-gb/articles/360020067139-API-access
- football-data.co.uk: https://www.football-data.co.uk/data.php
- Betfair BSP CSV: https://promo.betfair.com/betfairsp/SP_history.html
- pmxt Data Archive: https://archive.pmxt.dev/

## Related

- [[Venue-Alternatives-2026-04]] — exhaustive first-pass survey commissioned 2026-04-22
- [[Venue-Alternatives-2026-04-deep]] — deep-dive second pass; Matchbook billing clarification, Polymarket re-examination, data matrix, historical data matrix
- `CLAUDE.md` — venue list should reflect Matchbook as primary, Smarkets/Betfair deferred
- `docs/superpowers/plans/2026-04-20-phase6-7-roadmap.md` — Phase 7a primary execution crate to change from `execution-smarkets` to `execution-matchbook`
- `wiki/20-Markets/Betfair-Research.md` — existing Betfair research still valid; venue ranking: Delayed for data-only research, Live for execution (deferred)
- [[Polymarket-Feasibility-2026]] — canonical fact-check for the Polymarket deferral; see also deep-dive §3 for second re-examination verdict

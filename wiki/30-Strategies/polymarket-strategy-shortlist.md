---
title: "Polymarket Strategy Shortlist — Candidates for ≤£1k Capital"
type: research
tags: [polymarket, strategy, research, shortlist]
status: active
created: 2026-04-24
updated: 2026-04-24
---

# Polymarket Strategy Shortlist — Candidates for ≤£1k Capital

## Framing

The operator has committed to Polymarket-only execution (see `wiki/20-Markets/Venue-Strategy.md` 2026-04-24 update) and has already weighed and accepted the legal, regulatory, and platform-risk trade-offs. This note is purely a **strategy-microstructure** pass: which candidate edges plausibly survive a retail operator's constraints (≤£1,000 per strategy, 5 s Gamma polling today, CLOB `/book` and WebSocket reachable but not yet wired) after accounting for the known adverse-selection reality.

**Operator has already decided note:** the devil's-advocate pass on venue selection, legality, USDC handling, and CGT is out of scope here. The critiques below are strategy-grade only.

### Hard constraints shaping the shortlist

1. **Capital cap.** £1,000 hard ceiling per strategy. At Polymarket's typical tick grid (1¢ or 0.1¢ on high-liquidity books; `orderPriceMinTickSize` per market), a £1,000 budget translates to ~1,250 USDC at current FX. That supports ~6–20 concurrent positions at £50–£200 notional.
2. **Fee arithmetic.** March 2026 taker fees: Politics 1.00%, Finance 1.00%, Sports 0.75%, Tech 1.00%, Culture 1.25%, Weather 1.25%, Economics 1.50%, Mentions 1.56%, Crypto 1.80%. Fees are **symmetric around 50%** — a trade at 30¢ pays the same absolute USDC as a trade at 70¢ — so round-trip drag on a round-trip 50¢ trade is effectively 2× the taker rate on notional, i.e. ~2% on politics, ~3.6% on crypto. Geopolitics remains fee-free. ([Polymarket Fees Breakdown](https://www.tradetheoutcome.com/polymarket-fees/), [Medium — fee expansion](https://medium.com/coinmonks/polymarket-just-changed-its-fees-heres-what-bot-traders-need-to-know-c11132e55d5c))
3. **Maker rebates exist but are competitive.** 25% of taker fee in most categories (20% in Crypto); payouts pro-rata to `fee_equivalent = C × feeRate × p × (1 − p)` per market; $1 USDC minimum payout; no whitelist. Rebates do **not** offset adverse selection — they are paid on liquidity that got **taken**, and takers are disproportionately informed. ([Maker Rebates docs](https://docs.polymarket.com/developers/market-makers/maker-rebates-program), [Help Center](https://help.polymarket.com/en/articles/13364471-maker-rebates-program))
4. **Adverse selection is quantified and severe.** Akey, Grégoire, Harvie & Martineau (SSRN 6443103, 1.4M users, 70M trades, 2022–2025): 70.8% of users lose money; top 1% capture 84% of gains; **63% of retail trades are placed at <10¢ or >90¢** ("lottery-ticket" behaviour); being a maker rather than a taker reduces loss probability by **36 percentage points**. ([InGame summary](https://www.ingame.com/polymarket-academic-study-winners-losers-skewed/))
5. **Arb windows are closing.** Academic study covering April 2024–April 2025 (arXiv 2508.03474) finds 41% of conditions (7,051 / 17,218) had at least one arbitrage opportunity and $40M was extracted in the period, but secondary analysis reports median arbitrage duration fell from 12.3 s (2024) to **2.7 s (Q1 2026)**, with **73% of arb profit captured by sub-100ms execution bots**. Our 5 s Gamma poll alone cannot compete for these. ([arXiv 2508.03474](https://arxiv.org/html/2508.03474v1), [ILLUMINATION](https://medium.com/illumination/beyond-simple-arbitrage-4-polymarket-strategies-bots-actually-profit-from-in-2026-ddacc92c5b4f))
6. **Structural taker bias.** 5 s polling means any fill in our current adapter is against a taker who crossed our posted spread — except we're not posting. We are signal-driven and have to cross to enter, paying full fee + spread both ways. This disadvantages the entire mean-reversion class.

### Devil's-advocate concerns carried forward

- Concern 1 (winner-take-all) — any strategy must either (a) target markets small enough that professional flow ignores them, or (b) exploit structural/rule-based edges that don't require beating an informed counterparty.
- Concern 2 ($143M to informed traders, politics-heavy) — avoid directional politics trades, period.
- Concern 3 (5% round-trip) — edges under ~3% gross are dead on arrival in fee-enabled categories.
- Concern 6 (5 s polling → taker-only) — any strategy that fundamentally needs to be a maker to earn edge is deferred until WebSocket and off-chain signing are wired.

## Strategies killed before inclusion

These are listed so the reasoning is auditable; they do **not** appear in the shortlist below.

- **Mean-reversion on YES-mid (already scaffolded in `polymarket-yes-mean-revert.md`).** Mechanically crosses the spread on every entry; on a 2¢ spread in Politics, round-trip cost is ~4¢ (spread) + ~2¢ (fee on 50¢ trade) = 6% of notional, and reversion of 1 σ on a quiet market rarely exceeds 1–2¢. The `polymarket-yes-mean-revert` hypothesis treats the YES mid as a noise process, but the Akey et al. data shows Polymarket prices are well-calibrated on average, so "noise" is often genuine information moving the book. **Publish as a null hypothesis** — run paper, expect negative EV net of spread, use it to calibrate the simulator's optimism premium. Not recommended for live promotion.
- **News-latency fade of overshoot.** Requires either faster-than-market news ingestion (expensive; competes with Strategy 2 from the ILLUMINATION taxonomy) or faith that retail overshoot lasts >5 s on the move. For political/geopolitical news the 30–60 s overshoot window is plausible; for anything else it's closed inside our poll interval. Downgraded to "future, once WebSocket lands."
- **High-frequency momentum.** 8–15% monthly claims in industry content require sub-100ms orderbook access and dedicated Polygon RPC. Out of scope.
- **Professional market-making on liquid politics books.** Maker rebates are compressed sub-cent; incumbent MMs already sit on top of book. Entering this fight with £1,000 is a donation.

## Candidate 1 — Intra-market YES+NO complement arbitrage (with caveat)

**One-line description.** When YES best-ask + NO best-ask on the same condition sum to < $1 (minus fees), buy both and redeem for $1 at settlement.

**Edge mechanism.** YES and NO shares on the same binary condition are exact complements — one of them pays $1 at resolution, the other $0, and together they cost $1 to mint via the CTF `splitPosition` / settle for $1 via `redeemPositions`. Any time both asks sum below $1 by more than fees+gas, arb is locked. The Polymarket shared-orderbook design *mostly* closes this — selling YES at 0.4 is mechanically interpreted as buying NO at 0.6 — so pure YES-ask + NO-ask < $1 opportunities are rare on the same clobTokenId pair. ([KuCoin explainer](https://www.kucoin.com/news/flash/explaining-polymarket-why-yes-no-must-equal-1), [CTF Redeem docs](https://docs.polymarket.com/developers/CTF/redeem))

**Where the edge actually shows up.** Not on a single binary book (the matching engine collapses the two sides). It shows up on **multi-leg markets where the same underlying outcome is tradable in two distinct conditions** — e.g. an "Event X resolves YES by date D" market and a "Event X resolves YES by date D+7" market where the second is strictly weaker. These are logical-arbitrage instances, closer to Candidate 2 below. As a **pure single-condition** strategy, this is near-dead.

**Signal construction.** Cannot rely on Gamma — Gamma exposes YES best bid/ask for the primary CLOB token only. Needs CLOB `/book` fan-out for NO token (`clobTokenIds[1]`) to observe the NO side explicitly. Would require adapter extension to pull `/book` for both tokens on a curated watchlist.

**Capacity.** Near-zero. The arXiv 2508.03474 paper found single-market rebalancing is dominated by top arbitrageurs at sub-second latency. At £50–£200 size on a ~1% mispricing (which is itself rare post-fees), a single fill earns £0.50–£2 gross. Net of gas, slippage, and taker fee both legs, realized P&L per opportunity is likely negative unless the window is genuinely open for the ~2.7 s window at 5 s poll cadence — which is the opposite of the state of the world.

**Verdict.** **Skip as a standalone strategy.** Keep the `/book` fan-out capability on the roadmap because Candidate 2 needs it.

## Candidate 2 — negRisk basket arbitrage (MULTI-OUTCOME SUM ≠ 1)

**One-line description.** On Polymarket negRisk events (N mutually exclusive outcomes resolving to exactly one winner), buy all N YES shares whenever Σ best-ask(YES_i) < 1 − fees − buffer; or short all N (buy all N NOs) whenever Σ best-bid(YES_i) > 1 + fees + buffer.

**Edge mechanism.** The Neg Risk Adapter contract lets 1 NO on outcome i convert atomically into 1 YES on every *other* outcome, so the set {YES_1, …, YES_N} is tradeable as a mutually-exhaustive basket that resolves to exactly $1 regardless of which outcome wins. Whenever the sum of YES asks drops below $1 (or sum of bids rises above $1), there is a locked arb. This is the most-studied Polymarket inefficiency. ([Polymarket negRisk docs](https://docs.polymarket.com/advanced/neg-risk), [arXiv 2508.03474](https://arxiv.org/html/2508.03474v1))

**Empirical support.** arXiv 2508.03474 finds **42% of negRisk markets (662 of 1,578)** had at least one arbitrage opportunity over Apr 2024–Apr 2025; $40M total extracted across all arb types. Typical per-opportunity edge per QuantPedia / DeFi Rate colour is 2–5¢ per $1 basket, so 2–5% gross per fill before fees. Fee round-trip on an N-leg basket at mid prices across legs averages N × feeRate × p × (1 − p) summed over legs — on a 4-outcome politics basket with equal probabilities (p=0.25, 1-p=0.75, weight 0.1875 per leg), round-trip fee is ≈ 4 × 0.01 × 0.1875 = 0.75¢ per $1 basket, so **net 1.25–4.25¢ per $1**.

**Signal construction.** Needs:
- Gamma `/markets` with `negRisk=true` filter and `events` grouping — Gamma already exposes `negRisk` and `events[].markets[]`. This gets the basket roster for free at 5 s.
- CLOB `/book` fan-out for each `clobTokenIds[0]` in the basket — without depth, `bestAsk` is a price with unknown size; a 1¢ edge at 10 USDC depth isn't worth placing when a single £100 leg moves the book.
- On opportunity detection, N simultaneous IOC orders (or a basket order via neg-risk-ctf-adapter) — this is off-chain signing against Polygon and is **new infrastructure** relative to the current adapter.

**Capacity at £50–£200 size.** The binding constraint is the thinnest leg. Top-of-book depth on fast-moving 2-outcome political binaries is often $200–$1,000; on 4-way primaries and sports it can be $50–$300. A £50 basket (≈62 USDC) is realistic on the majority of negRisk events; £200 exceeds top-of-book on the tail. Opportunity pool: if 2.7 s arb windows exist on ~42% of negRisk markets and a UK-based 5 s poller observes a window once per ~10 total windows (Nyquist plus egress latency), with roughly 50–200 negRisk markets live at any time, realized opportunity count is ~1–5 fills/day at £50–£100 — call it £1–£20/day gross before slippage. **Total capital the pool supports: low four figures maximum, and declining.**

**Expected profile.** Directionally market-neutral post-basket-completion. Risk is in **leg-miss** (partial fill → directional exposure). Sharpe ill-defined at this frequency; gross win-rate should be >90% on filled baskets because the edge is structural. Hold horizon: if all legs fill, hold to resolution (days to weeks) or opportunistic close if the basket tightens back. Cost of carry: capital locked until resolution (weeks) unless we unwind on basket normalisation.

**Implementation cost.** **High.** Needs CLOB `/book` fan-out poller, basket order logic (N-leg atomic or compensating-cancel on partial fill), off-chain EIP-712 signing against Polygon, USDC/allowance management, and a simulator extension that understands basket fills rather than single-leg. Does **not** slot into the existing mean-reversion-shaped strategy runner without a new execution path.

**Promotion pathway.** **Cannot be meaningfully validated in simulation alone.** The alpha is in whether we actually fill all legs before the window closes, which depends on real Polygon block times, signing latency, and top-of-book race dynamics. Paper can confirm the *detection* logic; only live (small-size) fills validate the *execution* logic. Recommended gate: build detection + sim-fill → confirm opportunity count in practice → low-size live canary ($50–$100 per attempt, max 10 attempts) → scale.

**Known failure modes.**
- **Leg miss.** A 3-of-4 fill on a 4-leg basket leaves a directional short on the missing leg. On liquid politics this is bounded at ~(1 − p_leg) loss. Mitigation: IOC on all legs simultaneously with a "all-or-nothing" unwind on partial.
- **Fee mis-modelling.** The fee_equivalent curve peaks at p=0.5 and vanishes at the tails; on wide baskets (extreme p values across legs) fees are small, but also edges tend to be small.
- **Adverse selection on the last leg.** If we leave one leg till last, an informed trader can trade against us while we're still assembling. Mitigation: submit all legs in one Polygon tx (via adapter contract calls).
- **Oracle resolution risk.** A negRisk event that resolves ambiguously (UMA dispute) freezes basket value. Low but nonzero. Devil's-advocate concern 5 in full force.
- **Incumbents arb the window first.** The 2.7 s figure is median; at 5 s poll we miss half by construction. Survivable because (a) we target sub-$1000 size that larger bots ignore, and (b) windows on less-trafficked negRisk events (small sports props, weather, niche politics) last longer.

**Verdict.** **First-choice candidate.** The edge is structural (payout arithmetic), quantified in the academic literature, and sized to £50–£200 positions. It is the highest-confidence Polymarket strategy for this capital tier, even though it requires the most new infrastructure.

## Candidate 3 — Cross-venue sports arb vs Pinnacle / devigged book

**One-line description.** Fair-price a sports proposition from Pinnacle's two-way line (devigged), compare to Polymarket YES price on the same proposition, take the side where Polymarket deviates by more than fees + slippage + tracking error.

**Edge mechanism.** Pinnacle's closing line is the accepted sharp benchmark for sports fair-value; its margin is ~2% two-way, so devigging gives a fair probability with noise in the low tens of basis points. Polymarket sports markets are **retail-dominated** (per TheBoard.world / cryptonews / industry colour) and lag sharp book moves, especially during Asian overnight hours when Western market-making is thin. When Polymarket's YES implied price diverges from Pinnacle's devigged fair by >2% after fees, it is an edge against retail flow — not against informed Polymarket whales. ([TheBoard.world](https://theboard.world/articles/markets/prediction-market-trading-strategies-expert-edge/), [cryptonews — 2026 strategies](https://cryptonews.com/cryptocurrency/polymarket-strategies/))

**Signal construction.** Gamma `/markets` 5 s poll gives the Polymarket side (`sports` category, filter on `tags`). The Pinnacle side does **not** require a venue adapter — it's a read-only public odds feed. Options: scrape Pinnacle directly (risk of IP ban but free), use The Odds API (500 credits/mo free tier — listed in Venue-Strategy data-sources matrix), or OddsPapi (250 req/mo free). 5 s cadence is overkill for sports lines which move every 10–60 s anyway; 30 s poll on Pinnacle is sufficient.

**Capacity.** Directly constrained by Polymarket sports liquidity. Top-of-book on liquid single-match futures/ML markets is often $500–$5,000; on props and live markets $50–$500. £50–£200 per position is realistic on ~80% of live sports markets. **Opportunity pool easily supports £1,000+ capital** — sports is the deepest Polymarket vertical by volume.

**Expected profile.** This is the closest thing Polymarket offers to a "classic" positive-expected-value bettor strategy. Edge magnitude depends on latency vs sharp book: industry analyses report Polymarket sports prices lag Pinnacle by "hours" during off-peak windows (India/Asia overnight). A 2–4% post-fee edge per signal, at ~1–5 signals/day on a curated watchlist, is not unreasonable. Win-rate: expect 52–58% on positive-EV picks (near coin-flip when devigging is good; moneylines and totals are less noisy than props). Sharpe on a daily P&L: unknown and likely modest (0.5–1.5) at this scale before transaction costs dominate. Hold horizon: minutes to hours (close on convergence) or to resolution (settlement).

**Implementation cost.** **Low-medium.** Needs a Pinnacle / Odds-API ingestion adapter — but only as a **signal** feed, not a venue (no orders). The existing ingestion service already has a multi-source pattern. Strategy slots directly into the existing signal-driven runner: Polymarket side uses the existing `polymarket_adapter`, Pinnacle side is a new read-only ingestion. Orders only go to Polymarket.

**Promotion pathway.** **Highly simulator-friendly.** The edge is in pricing, not execution latency. Paper-trading the signal against simulated Polymarket fills (with realistic 5 s poll-miss probabilities) is a faithful test of signal quality. Promotion gate: 4 weeks of paper showing positive post-fee EV with reasonable Sharpe → small live canary → scale.

**Known failure modes.**
- **Pinnacle ToS / IP blocks.** Pinnacle explicitly discourages scraping; UK is geoblocked at the retail UI (commercial API also gone as of Jul 2025 per Venue-Strategy.md). Use The Odds API or OddsPapi instead — but acknowledge they may aggregate Pinnacle indirectly with their own latency.
- **Market-mapping overhead.** Polymarket sports descriptions are freeform; Pinnacle props are structured. A manual or LLM-assisted market-mapping layer is required and is a source of tracking error on exotic props.
- **Reg-change risk.** The 2026-04 Wisconsin / Kalshi sports-betting prediction-market lawsuits show regulators are actively re-drawing the sports-prediction-market boundary. Doesn't affect paper; could affect live capital-at-risk if markets are yanked mid-position. ([CoinDesk](https://www.coindesk.com/policy/2026/04/24/wisconsin-joins-prediction-market-fight-suing-kalshi-coinbase-polymarket-robinhood-and-crypto-com))
- **Fee erosion on short-horizon closes.** If we enter at 2% edge and close when the gap narrows to 0.5%, we've captured 1.5% gross and paid ~1.5% round-trip fee on Polymarket (Sports: 0.75% each way). Break-even. Must hold to resolution or to a deeper convergence.
- **Whose side is sharp?** The academic finding that **Polymarket prices are well-calibrated at 4 hours to expiry** (96–97% accuracy) weakens the "Polymarket lags sharp book" claim near close. Edge concentrates in pre-game and live-early windows, not last-minute.
- **Sportsbook outages / bad prints** — Pinnacle occasionally shows stale prices; blindly trusting a single feed as "fair" is dangerous. Use a two-source devig (e.g. Pinnacle + one other sharp).

**Verdict.** **Second-choice candidate, possibly first on implementation ease.** Lower edge per trade than Candidate 2, but ~10× the opportunity pool, existing infra fits, and clear simulator-validated promotion path. Strong alignment with "edges where retail flow is on the other side, not informed flow."

## Candidate 4 — New-listing / opening-book mispricing on low-volume, non-politics markets

**One-line description.** Watch Gamma for newly-listed markets (age < 2 h, `volume24hr` < $5k) where the book has opened away from a defensible prior (public data, precedent markets, base rate), and take the side that's mis-set before real flow arrives.

**Edge mechanism.** Polymarket new markets open seeded by the creator or a designated MM at a chosen price — often ~50¢ as an uninformed prior. For markets with a **known external prior** (e.g. "Will UK CPI in month M exceed X%" — ONS consensus exists; "Will temperature at LHR on date D exceed Y" — historical distribution known; "Will Premier League match M end with over 2.5 goals" — Pinnacle already prices this), the opening price frequently ignores the prior for the first minutes-to-hours until informed flow rebalances. This is the "5 s polling means structurally taker-only" concern turned upside down: the market is slow to discover price, and retail hasn't arrived yet to front-run us. ([arbitrage patterns](https://www.quantvps.com/blog/polymarket-hft-traders-use-ai-arbitrage-mispricing))

**Signal construction.** Gamma `/markets` exposes market creation time, `volume24hr`, `liquidityClob`, `oneDayPriceChange`. Filter: `created_at > now - 2h AND volume24hr < $5k AND category != politics AND category != geopolitics` (avoid the most-informed verticals) AND a price-prior rule (manual or model-driven). 5 s Gamma polling is **more than sufficient** — the edge window is minutes-to-hours, not milliseconds.

**Capacity.** Inherently **capacity-constrained**. Thin by definition; taking more than top-of-book ladders the cost of entry rapidly. £50 per position, max £500 in open new-listing positions simultaneously. This is a **strategy**, not a scaling story.

**Expected profile.** High win-rate on correct prior-application (expect 60–75%) but low volume. Hold horizon: hours to days until the market "finds" its price. Edge per trade: varies wildly; 3–15¢ when the opening is genuinely off, near zero when the creator/MM priced it intelligently. Sharpe poor because opportunity count is low and position sizing can't compensate.

**Implementation cost.** **Low.** Slots into the existing strategy runner with a small "age + volume + prior" filter stage. Requires a **per-market-type prior function** (one for sports, one for weather, one for macro). No new infrastructure.

**Promotion pathway.** Paper-tradeable with caveat: simulator fills at mid on thin books are over-optimistic. Use conservative fill rules (fill only top-of-book, clip to 10% of available depth, slippage = 1 tick). Paper for 4–6 weeks, review per-category performance, promote the best two or three categories only.

**Known failure modes.**
- **Creator pre-fills the book correctly.** Sophisticated market creators (Polymarket itself, seeded MMs) don't leave 50¢ opens for informed priors. The edge exists on **user-created** or **lazily-seeded** markets, which Gamma doesn't flag directly — have to infer from initial-liquidity heuristics.
- **Survivorship bias.** "Markets that had price discovery" is observable ex post; "markets that will have price discovery before resolution" is what we bet on. Many new markets resolve before the mispricing closes, so the edge only realises on the slow-close subset.
- **Prior-function error.** A wrong prior model makes this a pure loss strategy. Each category needs its own prior, validated independently.
- **Opportunity decay.** If the strategy works, professional bots will build the same filter and arrive first. Edge half-life probably 6–12 months on any given category.
- **Politics/geopolitics carveout.** Hardest to price correctly (base rate = subjective), most informed flow. Explicitly excluded from the category filter.

**Verdict.** **Third-choice candidate, niche.** Slot for £100–£300 of capital at most, not a primary driver. Good to run as a learning strategy for validating the simulator's thin-book fill model.

## Candidate 5 — Illiquid-market spread harvesting on the NO side (speculative, deferred)

**One-line description.** On negRisk baskets with thin NO books, post resting NO bids at the statistical floor (floor given the basket's fair-value distribution of leg priors) and earn maker rebate on any taker that walks the book.

**Edge mechanism.** Most retail traders buy YES on their favoured outcome, which mechanically buys NO *from* anyone selling YES but also leaves unbalanced NO supply on underdog outcomes. On thin multi-leg markets, a patient NO bidder on a statistically-low-probability outcome (say, 10¢ on a 4% true-probability leg) collects the maker rebate (25% × 1% × 0.04 × 0.96 = ~1bp on fill) and the spread (6¢ if the ask is 16¢), while only being exposed if the underdog wins.

**Why it's speculative.** (1) Requires posting, which requires WebSocket + off-chain signing — same new-infra cost as Candidate 2. (2) The "patient bidder" strategy converges to "insurance-selling on tail outcomes" which has positive carry in good times and catastrophic negative carry on a single hit. Kelly-sizing is critical; £50 positions with £1,000 total cap survives a tail strike (loss = stake) and can absorb a ~95% hit rate over many trades. (3) Adverse-selection concern: a taker who walks the book to lift our NO at 10¢ probably knows something. Akey et al. finding that makers do 36 pp better than takers is averaged across all makers — it doesn't distinguish "good" (price-discovery-providing) makers from "gullible" (adverse-selected insurance sellers).

**Signal construction.** Needs CLOB `/book` (depth on NO tokens) and WebSocket (to keep orders live without getting run over by book moves). Gamma alone is insufficient.

**Capacity.** Capped by the number of thin underdog legs we can afford to insure simultaneously. At £50 per NO position, £1,000 supports 20 open tail bets. Opportunity pool is wide (hundreds of thin-leg negRisk outcomes live at any time); finding the *right* ones where our implied probability is higher than the true is the signal challenge.

**Expected profile.** Negative skew: many small wins (rebate + spread on unresolved books, or YES-side converging our way) punctuated by rare large losses (the underdog hits and our NO position pays 0). Win-rate nominally 85–95%; Sharpe moderate and highly regime-dependent. Hold horizon: to resolution (weeks to months) or opportunistic close.

**Implementation cost.** **High.** Same new infrastructure as Candidate 2 (WebSocket, off-chain signing) plus a prior-based underdog-probability model.

**Promotion pathway.** **Difficult to simulate honestly.** The strategy's core assumption — "we can stay at the top of a resting bid book without getting adversely selected" — can only be tested with real posted orders, because the simulator doesn't know who we'd be selected against in a live book. Defer until Candidate 2 has validated the WebSocket + signing stack live.

**Known failure modes.**
- **Single-event wipeout.** A tail leg hits while we have 10+ open NO insurance positions across correlated underdogs → loss of up to full stake × number of hits.
- **Model risk on underdog probabilities.** Thin-leg pricing requires either calibrated historical base rates (for weather / macro) or expert-model judgement (for politics / sports). Miscalibration is fatal.
- **Maker rebate compression.** Sophisticated MMs already sit on these books; our rebate share is pro-rata of `fee_equivalent × shares_filled`, which is small.
- **Carry compensation.** Capital locked in 20 thin positions for weeks has opportunity cost; if Candidate 2 or 3 has better return-on-capital, this strategy is dominated.

**Verdict.** **Watch-list, not shortlist.** Revisit after Candidate 2 is live and the WebSocket/signing stack exists. Do not build out of sequence.

## Comparison table

| Candidate | Edge source | Data needed beyond Gamma 5 s | Capacity at £50–£200/position | Infra cost | Paper-validate? | Rank |
|---|---|---|---|---|---|---|
| 2. negRisk basket arb | Rule-based (payout arithmetic) | CLOB `/book` fan-out + basket order path | ~20 positions, low-4-fig capital pool | High (WS or /book, off-chain sign, basket orders) | Partially (detection yes, execution no) | **1st** (highest confidence edge) |
| 3. Cross-venue sports | Pinnacle sharp vs retail-Polymarket lag | Pinnacle / Odds-API read-only feed | Wide — easily £1000+ | Low-medium (just a signal feed) | **Yes** — clean sim test | **1st** (lowest implementation risk) |
| 4. New-listing mispricing | Lazy opening prices vs external prior | None (Gamma suffices) | Narrow — £100–£300 total | Low (filter + prior fn) | Yes, with caveats on fill model | 3rd |
| 5. NO-side spread harvest | Maker rebate + underdog insurance | `/book` + WebSocket + off-chain sign | Wide but risky | High + risk model | Poorly — needs live | Deferred |
| 1. YES+NO same-condition | Payout complement | `/book` both tokens | Near-zero | Medium | Yes but not worth it | **Skip** |
| Null — YES mid-mean-revert | None (tested as null) | Current Gamma feed only | Any | Already scaffolded | Yes | **Run as null hypothesis** |

## Recommendation

**If I had to pick one to implement first, it would be Candidate 3 (cross-venue sports arb vs sharp book)**, because:

1. **It slots into existing infrastructure.** The Polymarket ingestion adapter is live; sports data is a read-only feed with no new signing, no wallet, no basket logic.
2. **It is paper-validatable.** Unlike Candidate 2, the edge is in *pricing*, not in *execution race conditions* — 4 weeks of paper-trading produces a credible EV estimate.
3. **The opposing flow is retail, not informed whales.** Akey et al.'s "63% of retail trades at extremes" and the industry colour on sports being the retail-dominated category both point the adverse-selection arrow away from us.
4. **Opportunity pool easily supports £1,000.** Sports is Polymarket's deepest vertical; capacity is the constraint least likely to bind.
5. **Low reversibility cost.** If the edge doesn't materialise in paper, we've added one read-only feed and a mapping layer. No wasted on-chain infrastructure.

Candidate 2 (negRisk basket arb) is structurally higher-edge per fill and is the right **second** target — but only after Candidate 3 has proven the end-to-end strategy-runner → Polymarket-simulator → promotion-gate loop works on a live feed. Building basket-order infrastructure against a loop that hasn't been debugged on a simpler strategy first is the classic premature-optimisation mistake.

The scaffolded `polymarket-yes-mean-revert` should stay in-tree but be **re-labelled as a null hypothesis** — its paper P&L is expected to be negative-or-zero net of spread, and running it in parallel serves as a sanity check on the simulator's fee/spread accounting. If it *does* show positive EV in paper, we should suspect the simulator before celebrating.

## Sources

Primary:
- Akey, Grégoire, Harvie & Martineau (SSRN 6443103) — "Who Wins and Who Loses In Prediction Markets?" — 1.4M users, 70M trades, 70.8% lose, top 1% capture 84%, maker-vs-taker 36 pp gap. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6443103 (403 at direct fetch; summary via https://www.ingame.com/polymarket-academic-study-winners-losers-skewed/)
- Unravelling the Probabilistic Forest (arXiv 2508.03474) — 86M on-chain transactions Apr 2024–Apr 2025; $40M arb extracted; 41% of conditions, 42% of negRisk markets exploitable. https://arxiv.org/abs/2508.03474 / https://arxiv.org/html/2508.03474v1
- Polymarket negRisk docs — https://docs.polymarket.com/advanced/neg-risk
- Polymarket CTF Redeem docs — https://docs.polymarket.com/developers/CTF/redeem
- Polymarket Maker Rebates — https://docs.polymarket.com/developers/market-makers/maker-rebates-program ; https://help.polymarket.com/en/articles/13364471-maker-rebates-program
- Polymarket CLOB WebSocket overview — `wss://ws-subscriptions-clob.polymarket.com/ws/market` (no auth), `…/ws/user` (auth). https://docs.polymarket.com/developers/CLOB/websocket/wss-overview
- neg-risk-ctf-adapter reference impl — https://github.com/Polymarket/neg-risk-ctf-adapter

Secondary:
- Polymarket fees 2026 update — https://medium.com/coinmonks/polymarket-just-changed-its-fees-heres-what-bot-traders-need-to-know-c11132e55d5c ; https://www.tradetheoutcome.com/polymarket-fees/ ; https://www.predictionhunt.com/blog/polymarket-fees-complete-guide
- ILLUMINATION — "Beyond Simple Arbitrage: 4 Polymarket Strategies Bots Actually Profit From in 2026" — includes the 2.7 s median arb duration / 73% sub-100ms capture claim. https://medium.com/illumination/beyond-simple-arbitrage-4-polymarket-strategies-bots-actually-profit-from-in-2026-ddacc92c5b4f
- TheBoard.world — Polymarket sports cross-book edge colour. https://theboard.world/articles/markets/prediction-market-trading-strategies-expert-edge/
- cryptonews 2026 strategies guide — https://cryptonews.com/cryptocurrency/polymarket-strategies/
- QuantPedia — systematic edges in prediction markets. https://quantpedia.com/systematic-edges-in-prediction-markets/
- QuantVPS HFT writeup — https://www.quantvps.com/blog/polymarket-hft-traders-use-ai-arbitrage-mispricing
- $143M informed-trader capture claim — https://www.mexc.com/news/988693

Internal:
- `wiki/20-Markets/Venue-Strategy.md` (2026-04-24 Polymarket-only update)
- `wiki/30-Strategies/polymarket-yes-mean-revert.md` (scaffolded null-hypothesis strategy)
- `services/ingestion/src/ingestion/polymarket_adapter.py` (existing Gamma 5 s poller; YES-only bid/ask; NO side pending `/book` fan-out)

## Related

- [[polymarket-yes-mean-revert]] — recommended re-label to "null hypothesis"
- [[mean-reversion-ref]] — template, not a Polymarket candidate
- [[../20-Markets/Venue-Strategy]] — venue decision log (Polymarket-only focus)

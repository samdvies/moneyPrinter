---
title: "Polymarket News-to-Price Lag"
type: strategy
strategy-id: polymarket-news-lag
venue: polymarket
status: hypothesis
author-agent: human
created: 2026-04-24
updated: 2026-04-24
module: tbd
parameters:
  reaction_window_seconds: 180
  min_headline_relevance_score: 0.7
  min_market_volume_24h_usd: 50000
  stake_gbp: "30.0"
  max_positions_per_headline: 3
  hold_seconds: 900
  venue: "polymarket"
promotion_thresholds:
  sharpe: 0.5
  max_dd_pct: -20
  hit_rate: 0.45
  p_value_sharpe: 0.05
  walkforward_degradation: 0.5
  oos_sharpe_min: 0.5
tags: [strategy, polymarket, hypothesis, news, event-driven]
---

# Polymarket News-to-Price Lag

## Hypothesis

For headline-driven Polymarket markets (politics, geopolitics,
macro-economic, sports), there is a 2-15 minute reprice window
between a market-moving headline landing on a monitored feed and
Polymarket's best bid/ask converging to the new fair value. A bot
with sub-30 s headline-to-order latency can enter inside this window
often enough, at high enough magnitude, to yield positive EV net of
fees and spread on £30-stake trades.

## Mechanism

1. Ingest headlines from a curated set of **alive** feeds (see Data
   requirement). Do not use `feeds.reuters.com` (deprecated years
   ago) or `nitter.net` (rate-limited near-dead since 2024).
2. For each new headline, compute an embedding and score relevance
   against each tracked market's description + keyword set. Require
   `relevance_score ≥ min_headline_relevance_score`.
3. Compare the current market price to the implied
   post-headline fair value from a per-market rule set (e.g.
   "Event X confirmed by AP/Reuters → YES should go to ≥0.95 within
   10 minutes"). If the current mid is more than ~5 cents below the
   implied target, enter YES BACK at best ask; inverse for
   contradictory headlines.
4. Hold for up to `hold_seconds` (15 minutes) or exit on first
   signal that reprice has completed (best ask within 2 cents of
   target).
5. Cap `max_positions_per_headline` at 3 — one headline typically
   affects a small set of related markets; avoid concentration.

## Why this might work

- Polymarket retail flow is demonstrably slow on headlines — the
  Akey et al. dataset shows 63% of retail trades land at <10¢ or >90¢
  (lottery behaviour), not on mid-band reprices where information
  actually propagates.
- The reprice window exists and is measurable: the arXiv 2508.03474
  arb-window study shows median arbitrage duration fell from 12.3 s
  (2024) to 2.7 s (Q1 2026) for **pure arb**, but headline-driven
  reprice is a different process — it's not arbitrage, it's price
  discovery under new information, and empirically runs minutes.
- Embedding-based market tagging is cheap (one `text-embedding-3-small`
  call per headline, <10ms) and solves the brittle-keyword problem
  the Twitter source's `TAGS = {...}` dict would suffer from.

## Why this might not work

- Specialist bots already do this faster. Sub-100ms execution bots
  captured 73% of arb profit per 2508.03474 secondary data. Headline
  reprice is slower, but a 30 s-latency retail setup is competing
  with 1-5 s latency specialist setups run by crypto-native shops
  who already operate on Polygon.
- Geopolitical / political markets are where the reprice signal is
  strongest and also where $143M has already been extracted by
  informed flow per the devil's-advocate pass. Our "relevance" score
  doesn't give us the insider's asymmetric-information advantage.
- Headline-to-resolution risk. A market can reprice violently on an
  unconfirmed rumour that later reverses. Our stop-loss semantics
  aren't defined yet — naive hold-to-target could suffer large
  drawdown if the reprice reverses inside `hold_seconds`.
- Feed aliveness maintenance cost. Feeds die and rate-limit. The
  Twitter source's feed list (Reuters RSS, nitter.net) is already
  dead; ours will decay too. This strategy carries ongoing
  maintenance burden.

## Parameters

| Param | Value | Notes |
|---|---|---|
| `reaction_window_seconds` | 180 | 3-minute ingestion-to-decision budget |
| `min_headline_relevance_score` | 0.7 | Cosine similarity; tune on OOS data |
| `min_market_volume_24h_usd` | 50000 | Need enough liquidity to fill £30 |
| `stake_gbp` | 30.0 | £30; 33 concurrent ≤ £1k cap |
| `max_positions_per_headline` | 3 | Concentration cap |
| `hold_seconds` | 900 | 15-minute max hold |

## Data requirement (NEW, not yet in repo)

- **News feeds.** Use feeds that are verified alive **today**:
  - AP News ([apnews.com/hub/ap-top-news/feed](https://apnews.com/hub/ap-top-news/feed))
  - Reuters official (not `feeds.reuters.com` — use
    `reuters.com/tools/rss/` or a paid tier if needed)
  - BBC Politics RSS (`feeds.bbci.co.uk/news/politics/rss.xml`)
  - White House press releases (`whitehouse.gov/feed/`)
  - Fed board press releases (`federalreserve.gov/feeds/press_all.xml`)
  - X/Twitter official API (authenticated; not nitter) for a
    curated account list (e.g. central banks, official agency accounts)
- **Embeddings.** Project uses xAI Grok (OpenAI-compatible). Grok has
  no embedding endpoint as of 2026-04; either (a) use OpenAI
  `text-embedding-3-small` via a narrow-scoped key for this
  workstream only, or (b) local `sentence-transformers` model.
  Route choice is a separate decision for the research orchestrator.
- **Market tagger.** Maintain `wiki/30-Strategies/news-tags/` mapping
  keyword-regex + embedding-centroid → market slug. Research
  orchestrator curates.

None of these are implemented today. News ingestion is its own
workstream; this hypothesis blocks on it.

## Risk posture

Paper only. Explicit stop: if mid moves **against** entry by more
than 5 cents inside the first 60 seconds, exit at market regardless
of `hold_seconds` remaining. (This avoids the rumour-reverses
drawdown mode.)

## Promotion gate

1. News ingestion workstream shipped; `market.news` topic populated
   with tagged headlines.
2. Walk-forward shows `mean_oos_sharpe ≥ 0.5` and beats
   `random-headline-entry` baseline at `p_value_sharpe ≤ 0.05`.
3. Fee-sensitivity sweep: EV positive at taker fee +25%.
4. Feed-death audit: strategy does not silently degrade when any
   one feed goes stale (sentinel: min headlines per hour threshold,
   alert not trade).
5. ≥ 2 weeks of paper data covering at least one major headline
   cluster (e.g. a Fed FOMC day or a US election resolution) —
   strategies that only work in calm regimes are useless.

## Explicitly NOT this strategy

- **Don't** ingest `nitter.net` or `feeds.reuters.com`. Both dead.
- **Don't** rely on LLM judgment for trade decisions. The tagger
  uses embeddings + deterministic rules; the validator is the
  existing deterministic `backtest_engine.promotion_gate`. LLMs
  propose headline→market mappings; they do not decide entries.

## Prior art note

[[polymarket-strategy-shortlist]] §"Strategies killed before
inclusion" downgraded "News-latency fade of overshoot" to "future,
once WebSocket lands." This note is a different formulation — not
fading retail overshoot, but capturing the initial reprice window
itself. Worth running through the gauntlet independently.

## Related

- [[polymarket-book-imbalance]] — short-horizon book signal;
  potential 4-layer alignment if both + whale-follow agree.
- [[polymarket-whale-follow]] — on-chain signal;
- [[polymarket-strategy-shortlist]] — context on which news feeds
  have been vetted and which haven't.

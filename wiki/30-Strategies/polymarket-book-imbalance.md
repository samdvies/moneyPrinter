---
title: "Polymarket CLOB Book-Imbalance Signal"
type: strategy
strategy-id: polymarket-book-imbalance
venue: polymarket
status: hypothesis
author-agent: human
created: 2026-04-24
updated: 2026-04-24
module: tbd
parameters:
  depth_levels: 5
  imbalance_enter: 0.6
  imbalance_exit: 0.1
  stake_gbp: "50.0"
  max_spread_bps: 200
  min_market_volume_24h_usd: 20000
  venue: "polymarket"
promotion_thresholds:
  sharpe: 0.5
  max_dd_pct: -20
  hit_rate: 0.45
  p_value_sharpe: 0.05
  walkforward_degradation: 0.5
  oos_sharpe_min: 0.5
tags: [strategy, polymarket, hypothesis, book-depth, order-flow]
---

# Polymarket CLOB Book-Imbalance Signal

## Hypothesis

On Polymarket CLOB markets, the top-5-level bid/ask size imbalance
flips ahead of 1-5 minute mid-price moves often enough, and with large
enough magnitude, to yield positive expected value **net of fees and
spread** on mid-volume markets ($20k-$500k 24h volume) where flow is
retail-dominated and under-hedged.

"Book imbalance" here means
`I = (Σ bid_size_i − Σ ask_size_i) / (Σ bid_size_i + Σ ask_size_i)`
summed over the top-5 levels on both sides. `I > 0` means weighted
buying pressure on YES.

## Mechanism

Per tick (target cadence 1 Hz once WebSocket ingestion lands; 5 s poll
acceptable as a paper-trading approximation):

1. Fetch `clob.polymarket.com/book?token_id=<YES_token>`; compute `I`
   across top `depth_levels` levels.
2. Compute previous-tick imbalance `I_prev` from rolling state.
3. Enter a YES BACK at best ask when `I` crosses above
   `imbalance_enter` from below; enter a YES LAY when `I` crosses
   below `-imbalance_enter` from above.
4. Exit when `|I| <= imbalance_exit` OR a 5-minute holding timer fires.
5. Skip markets where `best_ask - best_bid > max_spread_bps / 10_000`
   (spread too wide → round-trip fees + spread eat the signal).
6. Skip markets with 24h volume below `min_market_volume_24h_usd` (not
   enough flow to reprice on book signal alone) and above £500k
   equivalent (professional MMs already read this signal faster).

## Why this might work

- Retail taker flow on Polymarket is disproportionately
  "lottery-ticket" priced (>63% of retail trades at <10¢ or >90¢ per
  Akey et al. 2025). Mid-band flow (~20¢-80¢) is thinner and less
  adversely-selected, so a book-pressure signal there is less likely
  to be against informed takers.
- Maker rebates (25% of taker fee on most categories) partly offset
  entry cost **if** we can maker-fill on at least one leg of the
  round-trip. This strategy is taker on entry and potentially maker
  on exit.
- The Polymarket matching engine does not hide iceberg depth by
  default — top-of-book size is real, not a shadow.

## Why this might not work

- 5 s polling is structurally taker-only and loses the signal to
  sub-100ms bots (per 2508.03474 secondary data, 73% of arb profit
  goes to sub-100ms execution). If the signal has predictive value at
  1-5 minute horizon, latency may matter less; if it decays inside
  seconds, we are dead. Validation must isolate this.
- On the high-volume end (politics, liquid sports), professional MMs
  already sit on top of book and pre-price this signal. The
  `min/max_market_volume_24h_usd` gates are there specifically to
  keep us out of that fight.
- Fee drag: Politics taker 1.00%, Sports 0.75%, Crypto 1.80%. At 50¢
  mid a round-trip costs ~2× taker rate on notional; the enter-to-exit
  mid move has to clear that before edge is positive.

## Parameters

| Param | Value | Notes |
|---|---|---|
| `depth_levels` | 5 | Matches the Twitter "Hermes" framework; tunable |
| `imbalance_enter` | 0.6 | Threshold cross to enter |
| `imbalance_exit` | 0.1 | Tight exit once imbalance normalises |
| `stake_gbp` | 50.0 | £50 per position; 20 positions ≈ £1k cap |
| `max_spread_bps` | 200 | 2 cents at 50¢ mid; widen kills EV |
| `min_market_volume_24h_usd` | 20000 | Avoid dead books |

## Data requirement (blocker)

This strategy **cannot be validated today** because the current
`polymarket_adapter.py` emits `size=Decimal("0")` sentinels on YES
bid/ask and does not fetch the NO book at all. The
[[../../docs/superpowers/plans/2026-04-24-polymarket-clob-book-depth-ingestion|CLOB
book-depth ingestion plan]] must ship before this strategy's
`on_tick` sees real depth. Until then, any backtest on synthetic
random-walk data (like the seed strategy) will be meaningless for
this mechanism — the mechanism IS the book.

## Risk posture

Paper only. £1,000 per-strategy default cap applies. Because this
strategy enters on imbalance and exits on mean-reversion of imbalance,
max concurrent positions are bounded by
`stake_gbp × concurrent ≤ 1000` → ≤20 positions at £50.

## Promotion gate

Before any move toward `paper → awaiting-approval → live`:

1. Book-depth ingestion shipped and populating real `(price, size)`
   levels on `bids`/`asks` in `MarketData`.
2. ≥1 week of paper data with positive EV **net** of the simulator's
   optimism premium (see [[polymarket-yes-mean-revert]] §Risk posture
   for the null-hypothesis calibration this relies on).
3. Walk-forward gauntlet (`backtest_engine.validate`) passes:
   `mean_oos_sharpe ≥ 0.5`, degradation ratio ≥ 0.5,
   `p_value_sharpe ≤ 0.05` on `compare_to_random_baseline`.
4. Fee-sensitivity sweep: EV remains positive when the taker fee
   assumption is perturbed ±25% (protects against fee-schedule
   changes).

## Origin

Idea derived (stripped of its affiliate-link wrapper) from a Twitter
post recommending "Hermes" — a 4-layer Polymarket bot. See
[[polymarket-strategy-shortlist]] §"Strategies killed before
inclusion" for the operator's prior judgments on the related ideas in
that post. This book-imbalance mechanism was **not** explicitly
killed there and is filed here for the research orchestrator to code,
backtest, and adjudicate via the promotion gate — not to mirror any
particular wallet.

## Related

- [[polymarket-yes-mean-revert]] — seed strategy; this is a
  mid-horizon flow-pressure variant on the same YES-mid process.
- [[polymarket-strategy-shortlist]] — curated shortlist; this note
  expands Candidate-class "order-flow" strategies.

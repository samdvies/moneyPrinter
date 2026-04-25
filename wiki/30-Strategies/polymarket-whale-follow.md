---
title: "Polymarket Whale-Follow (On-Chain Position Delta)"
type: strategy
strategy-id: polymarket-whale-follow
venue: polymarket
status: hypothesis
author-agent: human
created: 2026-04-24
updated: 2026-04-24
module: tbd
parameters:
  leaderboard_lookback_days: 90
  min_resolved_markets: 50
  min_realised_win_rate: 0.60
  top_n_wallets: 200
  rebuild_cadence_days: 7
  min_wallet_delta_usd: 500
  follow_lag_seconds: 30
  stake_gbp: "25.0"
  hold_until: "mirror-exit-or-resolution"
  venue: "polymarket"
promotion_thresholds:
  sharpe: 0.5
  max_dd_pct: -20
  hit_rate: 0.45
  p_value_sharpe: 0.05
  walkforward_degradation: 0.5
  oos_sharpe_min: 0.5
tags: [strategy, polymarket, hypothesis, on-chain, whale-follow, adverse-selection]
---

# Polymarket Whale-Follow (On-Chain Position Delta)

## Hypothesis

A filtered cohort of Polymarket wallets, selected by **realized** P&L
and resolution count over the trailing 90 days, continues to carry
enough forward predictive power on their new positions — **after**
realistic detection latency, fees, and survivorship-bias correction —
to yield positive expected value at £25 per mirror trade.

This is filed as a falsifiable hypothesis because the consensus
academic and microstructure literature suggests the forward edge is
small-to-zero once you correct for selection bias (Akey et al. 2025:
top 1% capture 84% of gains, but past winners regress hard). The goal
is to **measure**, not to assume.

## Mechanism

1. Every `rebuild_cadence_days`, rebuild the whale watchlist from
   `data-api.polymarket.com/leaderboards`:
   - Restrict to wallets with `≥ min_resolved_markets` resolved
     positions in the trailing `leaderboard_lookback_days` window.
   - Compute **realized** win rate and realized P&L (excluding
     unrealized marks — see `rn1` counter-example in
     [[polymarket-strategy-shortlist]] framing).
   - Keep the top `top_n_wallets` by realized P&L.
2. Snapshot watched wallets' positions every tick (target 30 s via
   Polygon RPC on the CTF exchange contract; degraded fallback is
   `data-api.polymarket.com/positions?user=<addr>`).
3. On a position **delta** (open a new market, or add to an existing
   one) of magnitude ≥ `min_wallet_delta_usd`:
   - Sleep `follow_lag_seconds` (models realistic detection +
     ingestion latency; do **not** assume instant follow).
   - Enter on the same side, at `stake_gbp`, with a taker order.
4. Exit when the mirrored wallet exits OR at market resolution.
5. Never mirror a wallet's exit signal alone — only their opens/adds.
   Exits can be tax-, liquidity-, or cash-driven and are noise for us.

## Survivorship-bias controls (non-negotiable)

1. **Use out-of-sample walk-forward**: rebuild the watchlist on
   in-sample window [T-180d, T-90d]; forward-test on [T-90d, T]. Do
   not let any resolution from the forward window leak into the
   selection.
2. **Include a "dead whales" cohort**: track wallets that were in the
   top decile 180 days ago but have since dropped out. Their forward
   performance is the counterfactual for "what regression to the mean
   looks like."
3. **Baseline**: a random-wallet cohort of the same size from the
   active-trader universe. If whale-follow does not beat this random
   baseline in `compare_to_random_baseline`, the strategy is dead.

## Why this might work

- Polymarket on-chain positions are **public**, timestamped, and
  linkable across markets. That's a strictly richer dataset than
  standard centralized-book trading.
- The Akey et al. study found top 1% of users capture 84% of
  aggregate gains. If that concentration is persistent at the
  individual-wallet level (and not just the population level), there
  is some signal — but the study itself doesn't prove wallet-level
  persistence.

## Why this might not work

- Survivorship bias. "Top 200 wallets with ≥60% realized win rate" is
  a cohort selected conditional on past outperformance, which
  regresses hard. Classic empirical result in equities factor research
  (e.g. DeMiguel et al. 2009 on mean-variance portfolios). The
  controls above exist specifically because this failure mode is the
  default.
- Adverse selection flips. If a wallet is "smart money" relative to
  retail, we — with a 30 s detection lag — are the marginal retail
  taker they are trading against. Their edge may be *our* cost.
- Wallet attribution drift. Whales use multiple wallets; private-key
  rotation breaks the history. The leaderboard only sees what's been
  attributed.
- On-chain detection latency. Polygon block time is ~2 s; confirmation
  depth + RPC poll + our processing realistically adds 10-30 s. The
  `follow_lag_seconds = 30` default is a conservative estimate; it
  must be validated against real block-timestamp data.

## Parameters

| Param | Value | Notes |
|---|---|---|
| `leaderboard_lookback_days` | 90 | Selection window |
| `min_resolved_markets` | 50 | Filter against low-sample luck |
| `min_realised_win_rate` | 0.60 | Realized, not unrealized (avoid `rn1` trap) |
| `top_n_wallets` | 200 | Watchlist size |
| `min_wallet_delta_usd` | 500 | Ignore dust position changes |
| `follow_lag_seconds` | 30 | Models realistic on-chain detection |
| `stake_gbp` | 25.0 | Small; 40 concurrent mirrors ≤ £1k cap |

## Data requirement

- `data-api.polymarket.com/leaderboards` — watchlist rebuild
- `data-api.polymarket.com/positions?user=<addr>` — per-wallet position snapshot
- (Optional, lower-latency) Polygon RPC on the CTF exchange contract
  at the user's chosen node (Alchemy, Ankr, or self-hosted)

None of these are implemented today. This hypothesis blocks on a
separate ingestion workstream (`polymarket_onchain_adapter.py` —
not yet planned) to pull positions + deltas into Redis Streams
topic `market.onchain` as a new message class.

## Risk posture

Paper only. Per-strategy cap £1,000. Because this strategy holds
until the mirrored wallet exits or the market resolves, expected
position duration is long (hours to days); concurrent exposure is
the real constraint, not trade frequency.

## Promotion gate

Before any move toward `paper → awaiting-approval → live`:

1. On-chain ingestion workstream shipped; positions topic populated.
2. Walk-forward with survivorship controls above shows
   `mean_oos_sharpe ≥ 0.5` AND beats `random-wallet` baseline at
   `p_value_sharpe ≤ 0.05`.
3. "Dead-whales" cohort forward-tests as expected regression to zero
   — if dead whales look the same as active whales forward, the
   signal is spurious.
4. Paper-trade ≥ 2 weeks (longer than book-imbalance because
   hold-to-exit semantics mean fewer round-trips and slower P&L
   convergence).

## Explicitly NOT this strategy

- **Don't** mirror a single wallet. `rn1` in the Twitter source post
  is ranked #7 on the leaderboard, 42% true win rate, $2.68M
  unrealized losses — a live demonstration that leaderboard rank ≠
  edge. This strategy mirrors a *filtered cohort* on *delta signals*,
  not a single wallet on *position state*.
- **Don't** subscribe to any third-party "copy-trade" Telegram bot.
  The operator has explicitly ruled this out.

## Related

- [[polymarket-book-imbalance]] — complementary real-time signal;
  potential alignment rule if both fire same direction.
- [[polymarket-strategy-shortlist]] — Candidate 3 "insider-flow /
  whale follow" was flagged as the highest-potential on-chain-native
  edge; this note is its concrete hypothesis form.

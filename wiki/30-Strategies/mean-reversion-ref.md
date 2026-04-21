---
title: "Mean Reversion (reference)"
type: strategy
strategy-id: mean-reversion-ref
venue: betfair
status: hypothesis
author-agent: human
created: 2026-04-20
updated: 2026-04-20
module: backtest_engine.strategies.mean_reversion
parameters:
  window_size: 30
  z_threshold: 1.5
  stake_gbp: "10"
  venue: "betfair"
tags: [strategy, betfair, mean-reversion, hypothesis]
---

# Mean Reversion (reference)

## Hypothesis
Mid-price mean-reverts on short horizons on liquid Betfair books. On a
reasonably populated order book, short-lived order-flow imbalances push the
mid-price temporarily away from a slower-moving fair value. Over a window
of a few tens of ticks the mid tends to drift back toward the window mean,
so a fade of extreme deviations should capture a small, repeatable edge.

## Mechanism
- Maintain a rolling window of the last `window_size` mid-prices where
  `mid = (best_bid + best_ask) / 2`.
- Once the window is full, compute `mean` and `stddev` of the window and the
  z-score `z = (mid - mean) / stddev`.
- If `z < -z_threshold`: emit a BACK at `best_ask`, stake = `stake_gbp`
  (we expect the mid to revert upwards).
- If `z > +z_threshold`: emit a LAY at `best_bid`, stake = `stake_gbp`
  (we expect the mid to revert downwards).
- Otherwise: no signal.
- Position sizing is constant (`stake_gbp`). Exits are implicit: the next
  opposite-side signal closes the prior position at the fill price
  (harness settlement, not the strategy module's concern).

## Expected Edge & Risk
- Expected edge: small per trade — a few ticks of mid-reversion, net of
  spread cost paid on entry. The strategy crosses the spread on every entry,
  so `z_threshold` must be large enough that the expected reversion exceeds
  the spread round-trip.
- Max drawdown tolerance: unmeasured pending a real historical corpus;
  capped in practice by the `max_exposure_gbp` registry cap (default £1,000).
- Capital requirement: one `stake_gbp` per open position (constant-stake).
- Kelly fraction recommended: unknown pending paper-trading variance
  estimates — constant stake is the conservative placeholder.

**Edge claim (tested in harness):** on a mean-reverting synthetic price
series (random walk with a strong pull-to-mean term) the strategy should
produce `total_pnl_gbp > 0` and `win_rate > 0.5`. On a trending synthetic
series (random walk with drift) the strategy should produce
`total_pnl_gbp < 0`. Both directions are asserted by the Phase 6b.4
orchestrator integration tests — a rubber-stamp harness would score both
as wins, so the asymmetric result is the proof that the harness
discriminates.

## Backtest Results
- Period: _pending (filled by `research_orchestrator.wiki_writer` in 6b.5)_
- Trades: _pending_
- Win rate: _pending_
- Mean edge per trade: _pending_
- CLV: _pending_
- Sharpe (if applicable): _pending_
- Max drawdown observed: _pending_
- Link to backtest report: _pending_

## Paper Trading Results
- Period: _not yet paper-traded_
- P&L: _not yet paper-traded_
- CLV vs live: _not yet paper-traded_
- Divergence from backtest expectation: _not yet paper-traded_

## Approval Status
- [ ] Backtest passed threshold
- [ ] Paper trading >= 30 days
- [ ] Risk manager review
- [ ] **Human approval** (required before live)

## Failure Modes
- **Trending regime mis-classified as noise.** If the underlying price
  trends rather than reverts, every entry is taken against the trend and
  accumulates losses. The 6b.4 integration test asserts this explicitly
  on a trending synthetic series.
- **Window too short.** A small `window_size` makes `stddev` volatile and
  the z-score hyperactive — the strategy fires on ordinary tick noise.
- **Window too long.** A large `window_size` lags real shifts in fair
  value; reversion signals fire after the market has already moved.
- **Near-constant windows.** When `stddev` collapses toward zero the
  z-score explodes on any mid change. The module guards this with a
  `min_stddev` floor, but mis-tuning it would re-expose the failure.
- **Thin books.** On illiquid selections the best bid/ask gap is wide
  and reversion rarely exceeds the spread round-trip; expected value is
  negative before any edge is captured.
- **Missing book side.** On empty `bids` or `asks` the module returns
  `None`; if that happens frequently it silently starves the warmup
  window and the strategy never arms.

## Kill Switch Conditions
- Registry cap breach: `open_exposure_gbp >= max_exposure_gbp` halts all
  new signals (enforced by the risk manager, not this module).
- Rolling-window drawdown (post-6c): if 24h P&L breaches a configured
  drawdown floor, the orchestrator transitions the strategy to
  `retired`.
- Regime detector (post-6c): if the rolling window's autocorrelation
  turns positive (trend signature) for N consecutive windows, pause
  new entries until the regime flips back.

## Related
- Roadmap: [[../../docs/superpowers/plans/2026-04-20-phase6b-reference-strategy]]
- Strategy template: [[../90-Templates/Strategy-Template]]
- Venue notes: _pending Betfair microstructure notes under [[20-Markets/]]_
- Ancestor strategies: _none — this is the first hand-written reference
  strategy for the harness._

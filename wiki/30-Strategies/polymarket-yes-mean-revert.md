---
title: "Polymarket YES Mean Reversion (low-volume stat arb)"
type: strategy
strategy-id: polymarket-yes-mean-revert
venue: polymarket
status: hypothesis
author-agent: human
created: 2026-04-23
updated: 2026-04-23
module: backtest_engine.strategies.mean_reversion
parameters:
  window_size: 10
  z_threshold: 1.0
  stake_gbp: "1.0"
  min_stddev: 0.00000001
  venue: "polymarket"
promotion_thresholds:
  sharpe: 0.5
  max_dd_pct: -20
  hit_rate: 0.45
  p_value_sharpe: 0.05
  walkforward_degradation: 0.5
  oos_sharpe_min: 0.5
tags: [strategy, polymarket, mean-reversion, stat-arb, hypothesis]
---

# Polymarket YES Mean Reversion (low-volume stat arb)

## Hypothesis

Polymarket YES-token mid-prices exhibit short-horizon mean reversion.
With 5-second Gamma polling we observe one tick per market; a rolling
window of 60 ticks spans five minutes, short enough to treat as
statistical noise around a slower fair value rather than a directional
drift. Deviations beyond ±2σ are more likely noise than new information,
so fading them captures a small, high-frequency, direction-neutral edge
at minimal per-trade size.

## Mechanism

Identical to `mean-reversion-ref` — the module is venue-agnostic. At each
tick for a Polymarket YES token:

- Compute `mid = (best_bid + best_ask) / 2`.
- Append to a rolling window; once the window has `window_size` values,
  compute `mean` and `stddev` and the z-score `z = (mid - mean) / stddev`.
- If `z < -z_threshold`, emit a BACK at `best_ask` (fade the dip).
- If `z > +z_threshold`, emit a LAY at `best_bid` (fade the spike).
- Skip markets with empty books (NO tokens under the current adapter
  never fill because Gamma does not expose NO bid/ask).

Stakes are constant at `stake_gbp`; exits are implicit — the opposite-
side signal closes the prior position via simulator settlement.

## Parameters

| Param | Value | Notes |
|---|---|---|
| `window_size` | 60 | 5 minutes at 5 s poll |
| `z_threshold` | 2.0 | 2 σ deviation threshold |
| `stake_gbp` | 1.0 | £1 per signal = "low volume" |
| `min_stddev` | 0.0001 | Guard against stagnant windows |

## Risk posture

Paper only. Per-venue cap £50 default (`risk_venue_notionals['polymarket']`);
per-strategy max exposure £1 000 (project default). Fills are simulated
from the Gamma-derived book with `size = Decimal("0")` sentinels — real
fill quality cannot be inferred from paper results. The strategy's paper
P&L is a signal-quality test, not a capacity test.

## Promotion gate

Before any move toward `paper → awaiting-approval → live`:

1. ≥ 1 week of paper data with positive expected value net of simulator
   optimism premium.
2. Resolution of the NO-depth gap (either CLOB `/book` fan-out in the
   adapter or explicit YES-only strategy scope).
3. A separately-approved capital plan covering Polygon wallet funding,
   USDC CGT handling, and ToS §2.1.4 acceptance.

## Related

- [[mean-reversion-ref]] — Betfair reference; identical module, different
  parameters.
- `services/ingestion/src/ingestion/polymarket_adapter.py` — upstream
  data source.
- `services/strategy_runner/` — dispatch runtime.

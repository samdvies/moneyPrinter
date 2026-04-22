---
title: "<Strategy Name>"
type: strategy
strategy-id: <snake-case-id>
venue: <smarkets|betfair-delayed|forecastex>
status: hypothesis
generated_by: grok-hypothesis-pipeline
cycle_id: <cycle_id>
spec_sha256: <sha256-of-strategy-spec-json>
code_sha256: <sha256-of-compute-signal-source>
author-agent: research_orchestrator
created: <YYYY-MM-DD>
updated: <YYYY-MM-DD>
parameters:
  <param_name>: <default_value>
tags: [strategy, hypothesis, <venue>, <signal-type>]
---

# <Strategy Name>

## Hypothesis

<1–3 sentence rationale: what edge exists and why it should be there.>

## Mechanism

<Signal formula and logic in plain English. Reference the available features (best_bid, best_ask, mid, spread, book_imbalance, microprice, recent_mid_velocity, best_bid_depth, best_ask_depth).>

- Entry rule: <when to enter>
- Exit rule: <when to exit / implicit harness settlement>
- Parameters: <list key parameters and their search ranges>

## Expected Edge

<Brief statement of the anticipated alpha source.>

## Backtest Results

- Period: _pending_
- Trades: _pending_
- Win rate: _pending_
- Mean edge per trade: _pending_
- Sharpe: _pending_
- Max drawdown: _pending_
- Link to backtest report: _pending_

## Paper Trading Results

- Period: _not yet paper-traded_
- P&L: _not yet paper-traded_
- CLV vs live: _not yet paper-traded_

## Approval Status

- [ ] Backtest passed threshold
- [ ] Paper trading >= 30 days
- [ ] Risk manager review
- [ ] **Human approval** (required before live)

## Failure Modes

<List known or anticipated failure modes specific to this strategy.>

## Kill Switch Conditions

- Registry cap breach: `open_exposure_gbp >= max_exposure_gbp` halts all new signals.
- Rolling-window drawdown: if 24h P&L breaches the configured drawdown floor, transition to `retired`.

## Related

- Cycle report: `wiki/70-Daily/<YYYY-MM-DD>.md` (section: cycle_id)
- Strategy template: [[../90-Templates/Strategy-Template]]

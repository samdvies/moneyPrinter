---
title: "Missing on_tick fixture"
type: strategy
strategy-id: missing-on-tick
venue: betfair
status: hypothesis
author-agent: human
created: 2026-04-20
updated: 2026-04-21
module: backtest_engine.strategies._notick
parameters:
  stake_gbp: "10"
tags: [strategy, betfair, test-fixture]
---

Points at `backtest_engine.strategies._notick`: inside the allowed namespace,
imports cleanly, but has no `on_tick` attribute, so the loader must raise
`StrategyLoadError` from the structural check.

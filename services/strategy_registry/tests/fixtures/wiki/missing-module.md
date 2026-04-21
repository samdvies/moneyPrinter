---
title: "Missing-module fixture"
type: strategy
strategy-id: missing-module
venue: betfair
status: hypothesis
author-agent: human
created: 2026-04-20
updated: 2026-04-20
module: backtest_engine.strategies.nonexistent_module
parameters:
  stake_gbp: "10"
tags: [strategy, betfair, test-fixture]
---

Module path deliberately unresolvable — loader must propagate ModuleNotFoundError.

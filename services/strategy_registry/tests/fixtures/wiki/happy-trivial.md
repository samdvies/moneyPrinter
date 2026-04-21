---
title: "Happy-path trivial loader fixture"
type: strategy
strategy-id: happy-trivial
venue: betfair
status: hypothesis
author-agent: human
created: 2026-04-20
updated: 2026-04-20
module: backtest_engine.strategies.trivial
parameters:
  stake_gbp: "10"
  venue: "betfair"
tags: [strategy, betfair, test-fixture]
---

# Happy-path trivial loader fixture

Exists only so `test_wiki_loader.py` can exercise the loader happy path
against a module that actually imports (`backtest_engine.strategies.trivial`
from Phase 6a). Do not rely on this for any production wiring.

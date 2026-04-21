---
title: "Outside-namespace fixture"
type: strategy
strategy-id: outside-namespace
venue: betfair
status: hypothesis
author-agent: human
created: 2026-04-21
updated: 2026-04-21
module: os.path
parameters:
  stake_gbp: "10"
tags: [strategy, betfair, test-fixture]
---

Points at stdlib `os.path`: a real, importable module that is NOT under
`backtest_engine.strategies.*`.  The loader must raise `StrategyLoadError`
before calling `import_module`, blocking any side effects from the import.

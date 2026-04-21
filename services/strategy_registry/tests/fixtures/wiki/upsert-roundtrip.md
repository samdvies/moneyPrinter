---
title: "UPSERT integration fixture"
type: strategy
strategy-id: upsert-roundtrip
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

Fixture for the UPSERT integration test. The test rewrites this file in a
tmp_path copy between loads, so the on-disk content is immaterial beyond
initial frontmatter validity.

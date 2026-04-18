---
title: "<Strategy Name>"
type: strategy
tags: [strategy, <venue>, <sport-or-market>, <status>]
strategy-id: <short-slug>
venue: [betfair|kalshi|cross-venue]
status: [hypothesis|backtesting|paper|awaiting-approval|live|retired]
author-agent: <agent-id>
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# <Strategy Name>

## Hypothesis
One paragraph — what inefficiency do we believe exists? What causes it?

## Mechanism
How the strategy captures the inefficiency. Entry signal, exit signal, sizing rule.

## Expected Edge & Risk
- Expected edge: <bps or %>
- Max drawdown tolerance: <%>
- Capital requirement: <£>
- Kelly fraction recommended: <value>

## Backtest Results
- Period: <from> to <to>
- Trades: <n>
- Win rate: <%>
- Mean edge per trade: <%>
- CLV: <%>
- Sharpe (if applicable): <value>
- Max drawdown observed: <%>
- Link to backtest report: <path>

## Paper Trading Results
- Period: <from> to <to>
- P&L: <£>
- CLV vs live: <%>
- Divergence from backtest expectation: <comment>

## Approval Status
- [ ] Backtest passed threshold
- [ ] Paper trading ≥ 30 days
- [ ] Risk manager review
- [ ] **Human approval** (required before live)

## Failure Modes
List what could go wrong and how we detect it.

## Kill Switch Conditions
Concrete rules that halt this strategy automatically.

## Related
- Source papers: [[40-Papers/...]]
- Venue notes: [[20-Markets/...]]
- Ancestor strategies: [[30-Strategies/...]]

---
title: Devil's Advocate Review — Phase 4 Pre-Implementation
type: review
date: 2026-04-19
reviewer: devils-advocate
branch-at-review: cursor/phase4-risk-dashboard-orchestrator-3377
status: passed
---

# Devil's Advocate Review — Phase 4 Pre-Implementation

## Scope Reviewed

- `docs/superpowers/plans/2026-04-19-phase4a-risk-manager.md`
- `docs/superpowers/plans/2026-04-19-phase4b-dashboard-skeleton.md`
- `docs/superpowers/plans/2026-04-19-phase4c-research-orchestrator-scaffold.md`

## Gate #1 Outcome

### Initial pass

- **Verdict:** BLOCKED
- **Severity 1 blocker found:** Dashboard risk-alert route specified `XREAD BLOCK 0` as "non-blocking"; in Redis that blocks indefinitely and can hang HTTP requests.

### Plan revisions applied

1. Updated dashboard plan to require `XREAD` with no `BLOCK` parameter so requests return immediately.
2. Clarified risk-manager exposure language to explicitly state Phase 4 is a per-signal guard and cumulative open-exposure is deferred.
3. Added explicit `while True` + `async for bus.consume(...)` guidance in risk-manager engine task to match existing simulator pattern.
4. Added `unit` marker registration requirement in root pytest config task.
5. Updated plan verification commands to include required `SERVICE_NAME` env usage for importability checks.
6. Hardened orchestrator scaffold plan around unique slugs in `run_once` and matching test assertions.

### Rerun result

- **Verdict:** PASS
- **Severity 1 findings:** None
- **Required edits before implementation:** None

## Severity 2 / 3 Items (Non-Blocking)

- Integration tests that run `engine.run(...)` under short timeouts must account for `BusClient.consume()` blocking behavior between batches.
- Dashboard tests need fixture-level environment setup for required settings fields.
- Dashboard plan intentionally does not add a first-class `paper -> awaiting-approval` endpoint; this remains an operator workflow via strategy-registry tooling in this phase.
- `POST /strategies/{id}/approve` remains unauthenticated by design in this skeleton and is flagged with `TODO(auth)`.

## Residual Risks to Track

1. Cumulative per-strategy open exposure remains deferred to a later phase.
2. Approval endpoint auth remains deferred and must be implemented before production.
3. Current stream topology allows multiple consumer groups on `order.signals`; operational routing discipline remains important as services expand.

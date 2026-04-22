---
title: Devil's Advocate Review — Phase 4 Post-Implementation
type: review
date: 2026-04-19
reviewer: devils-advocate
branch-at-review: cursor/phase4-risk-dashboard-orchestrator-3377
status: passed
---

# Devil's Advocate Review — Phase 4 Post-Implementation

## Scope Reviewed

- `services/risk_manager/**`
- `services/dashboard/**`
- `services/research_orchestrator/**`
- Shared updates:
  - `services/common/src/algobet_common/config.py`
  - `pyproject.toml`
  - `mypy.ini`

## Gate #2 Outcome

- **Verdict:** PASS
- **Severity 1 findings:** None
- **New Severity 1 vs pre-implementation:** None

## Ranked Findings

### Severity 2

1. `mypy.ini` did not include `dashboard` and `research_orchestrator` source paths, risking incomplete type-check coverage.
2. Risk exposure enforcement is per-signal stake only; cumulative open exposure is still deferred.
3. Dashboard approve endpoint remains unauthenticated (`TODO(auth)`), acceptable for skeleton scope but must be completed before production use.

### Severity 3

1. Bus consume/ack semantics acknowledge entries even if downstream processing raises (existing design risk, not introduced in this phase).
2. Risk alerts endpoint reads stream entries from `"0"` via XREAD, which is acceptable for skeleton but not ideal for recency-focused dashboards.
3. Integration tests use a private `BusClient` attribute in one orchestrator test (`bus._url`) for Redis stream inspection.

## Mitigations Applied in This Phase

1. Added complete Phase 4 service scaffolds and tests while preserving promotion-gate invariants.
2. Enforced orchestrator hard block on transitions to `awaiting-approval` and `live` before any DB call.
3. Implemented risk-manager pre-flight checks with critical kill-switch semantics for live-mode signals.
4. Kept dashboard approval path routed through `strategy_registry.crud.transition` only.

## Deferred Items

1. Cumulative open-exposure enforcement (Phase 5+ risk hardening).
2. Authentication/authorization on dashboard approval endpoint (Phase 5 gate hardening).
3. Bus ack/retry semantics redesign, if required, in shared bus primitives.

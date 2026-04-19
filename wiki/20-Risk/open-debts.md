---
title: Risk Manager Open Debts
type: ledger
tags: [risk, debt, phase5]
updated: 2026-04-19
status: active
---

# Risk Manager Open Debts

This ledger tracks known risk-manager weaknesses that are deliberately deferred to a later phase. Each entry includes the problem, the risk it creates, and the remediation options.

---

## Debt 1 — Approved-but-Unplaced Race

**Phase introduced:** 5a
**Severity:** Medium (bounded by simulator consume lag, ~ms at hobbyist signal rates)

### Problem

When the risk manager approves a signal and publishes to `order.signals.approved`, it does not write an `orders` row. The simulator inserts the row later when it consumes the approved signal. If a burst of signals arrive before the simulator has written any order row, all of them read the same `strategy_total_liability_before` and all get approved, potentially breaching the strategy exposure cap.

The per-strategy advisory lock (`pg_advisory_xact_lock(hashtext('risk:exposure:' || strategy_id::text))`) serialises concurrent checks for the same strategy, but it does not prevent a burst from reading stale state before any simulator write lands.

The singleton advisory lock (`pg_try_advisory_lock(hashtext('risk:singleton'))`) limits exposure to one replica but does not close the inter-service window.

### Remediation options

**Option A — `order_id` in `OrderSignal` + risk-manager-writes-orders:** The risk manager generates an `order_id`, writes an `orders` row with `status='pending'` on approval, and includes `order_id` in the approved signal. The simulator then `UPDATE`s the row to `placed` or `filled`. The open-liability view immediately reflects the pending order after approval.

**Option B — `liability_reservations` table:** A separate table accumulates liability reservations created by the risk manager on approval and deleted by the simulator on order creation. The `open_order_liability` view unions in reservations. Avoids schema coupling between risk manager and orders table.

Both options require cross-service coordination and are out of Phase 5a scope.

---

## Debt 2 — Rust Execution Engine Lacks Independent Exposure Cap

**Phase introduced:** 4 (carried over)
**Severity:** Low (defence-in-depth gap; risk manager still blocks at ingress)

### Problem

The Rust execution engine (`execution/`) does not enforce an independent hard exposure cap. If the risk manager is misconfigured or bypassed, the execution engine places orders without a fallback limit.

### Remediation

Add a configurable `max_exposure_gbp` check in the Rust execution hot path, reading from the same `strategies` table row (or a local config copy). Alert and abort placement if the cap would be breached.

---

## Debt 3 — Partial-Fill Slack (`filled_stake` not persisted)

**Phase introduced:** 5a
**Severity:** Low (over-counts liability — safe, but wastes headroom)

### Problem

Orders with `status = 'partially_filled'` contribute their full `stake` to open liability because the schema does not persist `filled_stake`. In reality, only the unfilled portion remains at risk. This causes the risk manager to over-count liability for partially-filled orders, rejecting signals that would be safe given the true exposure.

### Remediation

Add a `filled_stake numeric(12,4) NOT NULL DEFAULT 0` column to `orders`. Update the `open_order_liability` view to subtract `filled_stake` from `stake` for `partially_filled` rows. The simulator and execution engine must populate `filled_stake` on every fill event.

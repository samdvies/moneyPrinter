---
title: Risk Manager Open Debts
type: ledger
tags: [risk, debt, phase5]
updated: 2026-04-20
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

---

## Debt 4 — Kalshi YES/NO Liability Math Latent Bug

**Phase introduced:** 5a
**Severity:** Low today (latent) — Medium if Phase 6 populates Kalshi `selection_id` non-null

### Problem

The `open_order_liability` view and `rules.check_exposure` treat Kalshi `yes`/`no` sides as back-equivalents and compute `back_winnings = SUM(stake * (price - 1))`. For Kalshi prices ∈ [0, 1], `price - 1` is negative, so `back_winnings` goes negative. Inside `LiabilityComponents.market_liability = max(0, back_stake - lay_stake, lay_liability - back_winnings)`, negative `back_winnings` inflates `win_outcome` via the double-negation, which is safe in isolation but produces incorrect netting when YES and NO orders on the same Kalshi market land in the **same group key**.

Today this is harmless because Phase 5a's documented convention is that Kalshi orders use `selection_id = NULL`, and the view's `COALESCE(selection_id, 'order:' || id::text)` makes every NULL-selection row its own group — no netting. If Phase 6 ingestion populates Kalshi `selection_id` (e.g., from ticker) and two orders land in the same group, the math will under-count risk for offsetting YES+NO positions and over-count for reinforcing ones.

### Remediation

Either (a) keep Kalshi `selection_id = NULL` forever (document it as a contract between ingestion and risk), or (b) split the view and rules by venue — for `venue='kalshi'`, `signal_liability = stake` (already correct) and `market_liability = SUM(stake)` (sum of USD-at-risk across open contracts). Option (b) is the clean fix.

---

## Debt 5 — Redis XADD Inside Advisory-Locked Transaction

**Phase introduced:** 5a
**Severity:** Low (latency ceiling, not correctness)

### Problem

`risk_manager/engine.py` wraps the exposure check and the `XADD` to `order.signals.approved` / `risk.alerts` in the same `async with _acquire_exposure_context(...)` block, which holds a `pg_advisory_xact_lock` for the duration. Redis round-trip latency (typically single-digit ms, but unbounded under contention) therefore extends per-strategy lock hold time linearly. At hobbyist signal rates this is invisible; under burst load every same-strategy signal serialises behind an external I/O call.

### Remediation

Narrow the lock scope: perform the exposure check inside the transaction, commit, then publish outside the lock. Acceptable because the `orders` table write still happens later (downstream of the simulator) — the lock only serialises the *check*, not the publish. Defer until burst rates justify the work.

---

## Debt 6 — Dashboard Auth Has No MFA

**Phase introduced:** 5b
**Severity:** Low while the dashboard is bound to localhost; Medium if the dashboard is ever exposed beyond the operator's own machine (e.g., via a Tailscale exit node, a VPN, or a reverse proxy).

### Problem

Phase 5b gates the approve endpoint behind a cookie-session login that checks an argon2id password hash plus a CSRF double-submit cookie. A single-factor password is the only thing standing between an attacker with compromised credentials and a live-capital promotion. Rate limits (S1-c) slow online brute force but do not defend against credential theft.

### Remediation

Add a `operator_totp_secret text` column to `operators` and an `/auth/totp/verify` step between `/auth/login` and session-issuance. Use `pyotp` (or similar) for RFC 6238 TOTP. The bootstrap CLI should print the provisioning URI as a QR-code-ready string. Optional: WebAuthn via `py_webauthn` for hardware-key support.

---

## Debt 7 — Dashboard Lacks an Audit Log Beyond `approved_by`

**Phase introduced:** 5b
**Severity:** Low today (hobbyist scale, single operator) — Medium once more than one operator can authenticate and any auth-gated route exists beyond `/approve`.

### Problem

The only operator action currently recorded is the `strategies.approved_by` column. Failed logins, session creation/destruction, and future auth-gated actions (e.g., kill-switch toggles, rate-limit overrides) leave no trace. Incident response — "who approved what, when, from where?" — currently requires grepping application logs, which are ephemeral.

### Remediation

Append-only `operator_actions` table: `(id uuid pk, operator_id uuid null, action text, target_type text, target_id uuid null, ts timestamptz default now(), client_ip text, payload jsonb)`. Write on every auth-gated route call (success and failure) via a small dependency that wraps the route handler. Retention policy: indefinite until it grows large enough to partition.

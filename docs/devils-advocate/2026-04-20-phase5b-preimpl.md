---
title: Devil's Advocate Review — Phase 5b Dashboard Auth (Pre-Implementation)
type: review
date: 2026-04-20
reviewer: devils-advocate
branch-at-review: main
status: blocked-then-revised
---

# Devil's Advocate Review — Phase 5b Dashboard Auth (Pre-Impl)

## Scope Reviewed

- `docs/superpowers/plans/2026-04-20-phase5b-dashboard-auth.md`

## Gate #1 Outcome

### Initial pass

- **Verdict:** BLOCKED
- **Severity 1 findings:** 3
- **Severity 2 findings:** 4
- **Severity 3 findings:** 3

### Severity 1 — must fix before implementation

#### S1-a. Naïve double-submit CSRF is weak against cookie-tossing

Plan relied on cookie-vs-header equality only. OWASP (CSRF Prevention Cheat Sheet) notes the naïve pattern is broken when an attacker can write cookies on the victim's origin — cookie-tossing via a sibling subdomain, a MITM on HTTP sub-resources, or an XSS-adjacent injection.

Sources:
- OWASP CSRF Prevention Cheat Sheet — "Disallowed Patterns": <https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html>

#### S1-b. `cookie_secure=False` default is a footgun

Plan shipped with `cookie_secure: bool = False` for dev-ergonomics. If the operator forgets to flip it in prod, the session cookie leaks over cleartext. For a gate controlling live capital, the default polarity must be fail-closed.

Sources:
- MDN `Set-Cookie` / `Secure` attribute: <https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie>

#### S1-c. Deferring login rate-limit to the debt ledger is wrong trade-off

Argon2id at default cost (~200 ms verify) does not prevent a concurrent attacker — parallelism=4 means four cores of contention per attempt, and the "bound to 127.0.0.1" assumption is the *hope*, not an enforced invariant. Adding `INCR`+`EXPIRE NX` via Redis is ~15 LoC; deferring costs more than landing it.

Sources:
- OWASP Authentication Cheat Sheet — "Protect Against Automated Attacks": <https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html>

### Severity 2

- **S2-a.** `test_login_rotates_session_on_pre_auth_cookie` used a garbage token; the realistic attack uses a valid attacker-owned token. Coverage gap.
- **S2-b.** Timing-parity test with 50 ms tolerance will flap in CI. Needs (i) a deterministic invariant test (monkey-patch `verify_password` and count calls) and (ii) a looser smoke test.
- **S2-c.** `update_password` on the login hot path can race under concurrent rehash; needs compare-and-swap semantics.
- **S2-d.** No explicit end-to-end promotion test covering the full `HYPOTHESIS → BACKTESTING → PAPER → AWAITING_APPROVAL → /approve → LIVE` path hitting the session-sourced `approved_by`.

### Severity 3

- **S3-a.** Dependency ordering (`require_operator` before `require_csrf`) not documented; 401-vs-403 precedence under dual failure is an implicit contract.
- **S3-b.** Two-tab burst of concurrent approves on the same strategy — existing state-machine concern, not introduced by auth. Not a new risk.
- **S3-c.** Per-login CSRF rotation (plan's default) is OWASP-correct; worth explicitly noting.

### Calibration — what was already right

- `_DUMMY_HASH` computed at import time, not per request (correct).
- `hmac.compare_digest` for CSRF comparison (matches OWASP).
- Opaque Redis tokens over JWT (correct for single-operator system; avoids revocation complexity).
- Reads staying open is defensible for localhost-bound hobbyist deployment, and the plan is honest about the assumption.
- `HYPOTHESIS → LIVE` is not a valid state-machine edge; a compromised session grants only `awaiting-approval → live`, which is the intended privilege.
- State-machine invariants at `strategy_registry/transitions.py:86-92` and `crud.py:130` already enforce `approved_by` non-empty for the live transition. The route change is a strict strengthening, never a weakening.

## Plan Revisions Applied

1. **S1-a fix:** `require_csrf` now validates BOTH the double-submit header AND a matching `Origin` (or `Referer` fallback) against `settings.dashboard_allowed_origins`. New `validate_origin` helper in `auth/csrf.py`. New tests `test_approve_requires_matching_origin` and `test_approve_accepts_referer_when_origin_missing`.
2. **S1-b fix:** `cookie_secure` default flipped to `True`. Tests and local dev opt out via `COOKIE_SECURE=false` env.
3. **S1-c fix:** Rate-limit moved in-scope. New `auth/rate_limit.py` module, new integration test file `test_auth_rate_limit.py`, two new route-level tests (`test_login_rate_limit_by_ip`, `test_login_rate_limit_by_email`, `test_login_rate_limit_does_not_leak_distinction`). Rate-limit check runs *before* password verification so even malformed requests count against the quota. Lockout returns the generic 401 body identical to a wrong-password response.
4. **S2-a fix:** Test renamed `test_login_ignores_attackers_valid_session`. Creates two operators, logs in A to get a real token, injects that token on B's login request, asserts (a) B gets a new token, (b) A's token remains valid, (c) B's new token resolves to B. Documents that concurrent sessions survive login-induced rotation of a *presented* token.
5. **S2-b fix:** Two-tier timing test. The authoritative assertion is deterministic: monkey-patch `verify_password` with a counter, assert the unknown-email branch calls it exactly once (confirming the `_DUMMY_HASH` path). Wall-clock smoke test loosened to 150 ms using median-of-5 and marked `@pytest.mark.slow`.
6. **S2-c fix:** `update_password` contract is now compare-and-swap: `WHERE id=$1 AND password_hash=$old`. Returns True if the CAS wins, False (no-op) if another concurrent rehash already updated the row. Losing is not an error. CRUD tests updated to assert both branches.
7. **S2-d fix:** New test `test_approve_full_lifecycle_sets_session_email` walks the entire promotion path and asserts `approved_by == operator.email`.
8. **S3-a fix:** Safety invariants now document that `require_operator` is declared before `require_csrf` so 401 takes precedence over 403. New regression test `test_approve_auth_takes_precedence_over_csrf`.

### Rerun result (self)

- **Verdict:** PASS
- **Severity 1 findings:** None remaining in plan
- **Severity 2 findings:** None remaining in plan
- **Required edits before implementation:** None

## Residual Risks Tracked (post-revisions)

1. **No MFA** — documented in `wiki/20-Risk/open-debts.md`. Single-factor password auth is the only barrier.
2. **No audit log** beyond `approved_by` — documented. Login/logout/me calls are not persisted.
3. **Reads remain open** — `GET /strategies`, `GET /risk/alerts` are not gated. Assumption: local-network deployment. Flip to gated if exposed to untrusted networks.
4. **`cookie_secure=True` requires operator opt-out for local HTTP dev** — documented. Test fixture sets `COOKIE_SECURE=false`; production deployment over HTTPS needs no action.

## Sources

- OWASP CSRF Prevention Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html>
- OWASP Session Management Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html>
- OWASP Authentication Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html>
- MDN `Set-Cookie`: <https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie>
- argon2-cffi default parameters: <https://argon2-cffi.readthedocs.io/en/stable/parameters.html>

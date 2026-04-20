"""CSRF helpers — layered defence (double-submit cookie + Origin check).

Naïve double-submit is bypassable when an attacker can write cookies on
the victim's origin (cookie-tossing, MITM on HTTP sub-resources). OWASP
CSRF Prevention Cheat Sheet recommends pairing it with an Origin/Referer
check against a server-side allow-list. Both checks must pass.
"""

from __future__ import annotations

import hmac
import secrets


def issue_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def validate_csrf_header(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)


def _normalize(o: str) -> str:
    return o.rstrip("/")


def validate_origin(
    origin: str | None,
    referer: str | None,
    allowed: list[str],
) -> bool:
    """True iff Origin is in `allowed` (exact scheme+host+port) or, when
    Origin is absent, Referer starts with an allowed origin + `/`.

    An attacker's page can set arbitrary Referer but cannot set Origin,
    so Origin is the stronger signal when present.
    """
    norm_allowed = [_normalize(a) for a in allowed]
    if origin is not None:
        return _normalize(origin) in norm_allowed
    if referer is None:
        return False
    for allowed_origin in norm_allowed:
        if referer == allowed_origin or referer.startswith(allowed_origin + "/"):
            return True
    return False

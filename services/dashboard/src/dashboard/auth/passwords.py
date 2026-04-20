"""Argon2id password hashing wrapper for the dashboard auth subsystem.

A single module-level `PasswordHasher` is used with argon2-cffi's library
defaults (memory_cost=65536 KiB, time_cost=3, parallelism=4). The dummy hash
is generated once at import time and referenced by the login handler's
"user not found" branch to preserve timing parity with a real verify call.
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions

_HASHER: PasswordHasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _HASHER.hash(plain)


def verify_password(hashed: str, plain: str) -> bool:
    try:
        return _HASHER.verify(hashed, plain)
    except (argon2_exceptions.VerifyMismatchError, argon2_exceptions.InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _HASHER.check_needs_rehash(hashed)


# Computed once at import time; used by the login handler on the unknown-email
# branch to guarantee constant-ish verify latency. Never regenerate per request.
_DUMMY_HASH: str = hash_password(secrets.token_hex(16))

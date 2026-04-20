"""Unit tests for argon2id password hashing helpers."""

from __future__ import annotations

import pytest
from dashboard.auth.passwords import (
    _DUMMY_HASH,
    hash_password,
    needs_rehash,
    verify_password,
)

pytestmark = pytest.mark.unit


def test_hash_and_verify_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password(hashed, "correct horse battery staple") is True


def test_verify_wrong_password_returns_false_not_raises() -> None:
    hashed = hash_password("right")
    assert verify_password(hashed, "wrong") is False


def test_verify_malformed_hash_returns_false() -> None:
    assert verify_password("not-a-hash", "anything") is False


def test_needs_rehash_default_params_false() -> None:
    assert needs_rehash(hash_password("x")) is False


def test_dummy_hash_has_argon2id_prefix() -> None:
    assert _DUMMY_HASH.startswith("$argon2id$")

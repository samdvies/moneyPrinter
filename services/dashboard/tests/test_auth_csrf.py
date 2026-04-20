"""Unit tests for CSRF double-submit + origin-check helpers."""

from __future__ import annotations

import pytest
from dashboard.auth.csrf import issue_csrf_token, validate_csrf_header, validate_origin

pytestmark = pytest.mark.unit


ALLOWED = ["http://127.0.0.1:8000", "http://localhost:8000"]


def test_issue_token_nonempty_and_unique() -> None:
    a = issue_csrf_token()
    b = issue_csrf_token()
    assert a
    assert b
    assert a != b


def test_validate_csrf_header_happy_path() -> None:
    token = issue_csrf_token()
    assert validate_csrf_header(token, token) is True


def test_validate_csrf_header_mismatch() -> None:
    assert validate_csrf_header("a" * 30, "b" * 30) is False


def test_validate_csrf_header_cookie_none() -> None:
    assert validate_csrf_header(None, "x") is False


def test_validate_csrf_header_header_none() -> None:
    assert validate_csrf_header("x", None) is False


def test_validate_csrf_header_both_none() -> None:
    assert validate_csrf_header(None, None) is False


def test_validate_csrf_header_empty_string() -> None:
    assert validate_csrf_header("", "") is False


def test_validate_origin_matching_origin() -> None:
    assert validate_origin("http://127.0.0.1:8000", None, ALLOWED) is True


def test_validate_origin_referer_no_origin() -> None:
    assert validate_origin(None, "http://127.0.0.1:8000/dashboard", ALLOWED) is True


def test_validate_origin_both_none() -> None:
    assert validate_origin(None, None, ALLOWED) is False


def test_validate_origin_wrong_port() -> None:
    assert validate_origin("http://127.0.0.1:9999", None, ALLOWED) is False


def test_validate_origin_scheme_mismatch() -> None:
    assert validate_origin("https://127.0.0.1:8000", None, ALLOWED) is False


def test_validate_origin_referer_exact_root() -> None:
    assert validate_origin(None, "http://127.0.0.1:8000", ALLOWED) is True


def test_validate_origin_referer_on_foreign_host() -> None:
    assert validate_origin(None, "http://evil.example.com/x", ALLOWED) is False


def test_validate_origin_origin_on_foreign_host_even_with_good_referer() -> None:
    # Origin takes precedence; a foreign Origin fails even if Referer is valid.
    assert validate_origin("http://evil.example.com", "http://127.0.0.1:8000/x", ALLOWED) is False

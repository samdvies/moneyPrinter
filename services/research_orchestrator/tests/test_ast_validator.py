"""Tests for research_orchestrator.ast_validator.

Structure
---------
- Parametrized test over validator_allowed/ — every file must return ok=True.
- Parametrized test over validator_rejected/ — every file must return ok=False
  with at least one Violation.  For fixtures listed in EXPECTED_REASON_SUBSTRING
  the test also asserts that the expected substring appears in at least one
  violation's reason field.
- Targeted unit tests for edge cases: empty module, docstring-only module,
  nested FunctionDef rejection, allowed vs. rejected call targets, etc.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from research_orchestrator.ast_validator import (
    ALLOWED_CALLABLES,
    ALLOWED_IMPORTS,
    REJECTED_ATTR_NAMES,
    validate,
)

# ---------------------------------------------------------------------------
# Per-fixture expected reason substrings
# ---------------------------------------------------------------------------
# Maps fixture filename (stem) → substring expected in at least one violation
# reason for that fixture.  Fixtures not listed here only require ok=False and
# len(violations) >= 1 (backward-compatible default).
EXPECTED_REASON_SUBSTRING: dict[str, str] = {
    "reject_yield": "yield",
    "reject_yield_from": "yield from",
    # reject_await uses async def at module level; visit_Module catches it first.
    "reject_await": "AsyncFunctionDef",
    # reject_async_for/with both use async def; AsyncFunctionDef fires at module level.
    "reject_async_for": "AsyncFunctionDef",
    "reject_async_with": "AsyncFunctionDef",
    "reject_try_star": "TryStar",
    "reject_starred_args": "Starred",
    "reject_walrus": "walrus",
    "reject_match_statement": "match",
    "reject_call_in_default": "open",
    "reject_nested_function": "nested",
    "reject_assert": "assert",
    "reject_async_func_def": "AsyncFunctionDef",
    "reject_class_def": "ClassDef",
    "reject_compile_call": "compile",
    "reject_decorator": "decorator",
    "reject_delete": "delete",
    "reject_eval_call": "eval",
    "reject_exec_call": "exec",
    "reject_getattr_call": "getattr",
    "reject_global": "global",
    "reject_import_from": "ImportFrom",
    "reject_import_os": "os",
    "reject_lambda": "Lambda",
    "reject_module_level_assign": "module-level",
    # reject_nonlocal uses a nested function; nested FunctionDef fires first.
    "reject_nonlocal": "nested",
    # reject_open_call uses `with open(...)` — 'with statement' fires first.
    "reject_open_call": "with",
    "reject_raise": "raise",
    # reject_setattr_call uses snapshot.cached = 42 (attr assignment), not a setattr() call.
    "reject_setattr_call": "attribute target",
    "reject_try_except": "Try",
    "reject_with": "with",
    "reject_dunder_import_call": "__import__",
    "reject_attribute_target_assign": "attribute target",
    "reject_subscript_target_assign": "subscript target",
    "reject_comprehension_side_effect": "open",
    "reject_deep_attr_banned_leaf": "__class__",
}

# ---------------------------------------------------------------------------
# Fixture directories
# ---------------------------------------------------------------------------

_FIXTURES_ROOT = Path(__file__).parent / "fixtures"
_ALLOWED_DIR = _FIXTURES_ROOT / "validator_allowed"
_REJECTED_DIR = _FIXTURES_ROOT / "validator_rejected"


def _fixture_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.py") if p.name != "__init__.py")


# ---------------------------------------------------------------------------
# Parametrized: allowed fixtures must pass
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_path",
    _fixture_files(_ALLOWED_DIR),
    ids=lambda p: p.stem,
)
def test_allowed_fixture_passes(fixture_path: Path) -> None:
    source = fixture_path.read_text(encoding="utf-8")
    result = validate(source)
    assert result.ok is True, (
        f"Expected {fixture_path.name} to pass validation but got violations:\n"
        + "\n".join(f"  line {v.line}: [{v.node_type}] {v.reason}" for v in result.violations)
    )
    assert result.violations == ()
    assert result.module is not None


# ---------------------------------------------------------------------------
# Parametrized: rejected fixtures must fail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_path",
    _fixture_files(_REJECTED_DIR),
    ids=lambda p: p.stem,
)
def test_rejected_fixture_fails(fixture_path: Path) -> None:
    source = fixture_path.read_text(encoding="utf-8")
    result = validate(source)
    assert result.ok is False, f"Expected {fixture_path.name} to fail validation but it passed"
    assert (
        len(result.violations) >= 1
    ), f"{fixture_path.name} returned ok=False but no violations were recorded"

    # If a reason substring is registered, verify it appears in at least one violation.
    stem = fixture_path.stem
    if stem in EXPECTED_REASON_SUBSTRING:
        expected = EXPECTED_REASON_SUBSTRING[stem]
        assert any(expected.lower() in v.reason.lower() for v in result.violations), (
            f"{fixture_path.name}: expected reason containing '{expected}' but got:\n"
            + "\n".join(f"  [{v.node_type}] {v.reason}" for v in result.violations)
        )


# ---------------------------------------------------------------------------
# Fixture count sanity
# ---------------------------------------------------------------------------


def test_allowed_fixture_count() -> None:
    """At least 13 allowed fixtures must exist (10 original + 3 new)."""
    files = _fixture_files(_ALLOWED_DIR)
    assert len(files) >= 13, f"Only {len(files)} allowed fixtures found; expected >= 13"


def test_rejected_fixture_count() -> None:
    """At least 31 rejected fixtures must exist (20 original + 11 new)."""
    files = _fixture_files(_REJECTED_DIR)
    assert len(files) >= 31, f"Only {len(files)} rejected fixtures found; expected >= 31"


# ---------------------------------------------------------------------------
# Edge cases — empty / minimal modules
# ---------------------------------------------------------------------------


def test_empty_module_passes() -> None:
    result = validate("")
    assert result.ok is True
    assert result.violations == ()


def test_docstring_only_module_passes() -> None:
    source = '"""A module that only contains a docstring."""\n'
    result = validate(source)
    assert result.ok is True


def test_module_with_only_allowed_import_passes() -> None:
    source = "import math\n"
    result = validate(source)
    assert result.ok is True


def test_module_with_only_function_passes() -> None:
    source = "def f(x, y):\n    return x + y\n"
    result = validate(source)
    assert result.ok is True


# ---------------------------------------------------------------------------
# Syntax error handling
# ---------------------------------------------------------------------------


def test_syntax_error_returns_failure() -> None:
    result = validate("def f(:\n    pass\n")
    assert result.ok is False
    assert result.module is None
    assert len(result.violations) == 1
    assert result.violations[0].node_type == "SyntaxError"


# ---------------------------------------------------------------------------
# Module-level constraints
# ---------------------------------------------------------------------------


def test_module_level_assign_rejected() -> None:
    source = "X = 1\ndef f(s, p):\n    return X\n"
    result = validate(source)
    assert result.ok is False
    reasons = [v.reason for v in result.violations]
    assert any("module" in r.lower() and "assign" in r.lower() for r in reasons)


def test_module_level_expr_non_docstring_rejected() -> None:
    """A bare expression statement at module level that is NOT a string is rejected."""
    source = "1 + 2\ndef f(s, p):\n    return 1\n"
    result = validate(source)
    assert result.ok is False


def test_docstring_then_import_then_function_passes() -> None:
    source = (
        '"""Module docstring."""\n'
        "import math\n"
        "def f(snapshot, params):\n"
        "    return math.sqrt(float(snapshot['price']))\n"
    )
    result = validate(source)
    assert result.ok is True


# ---------------------------------------------------------------------------
# Import rules
# ---------------------------------------------------------------------------


def test_all_allowed_imports_pass() -> None:
    for mod in sorted(ALLOWED_IMPORTS):
        source = f"import {mod}\ndef f(s, p):\n    return None\n"
        result = validate(source)
        assert result.ok is True, f"import {mod} should be allowed"


def test_import_sys_rejected() -> None:
    source = "import sys\ndef f(s, p):\n    return None\n"
    result = validate(source)
    assert result.ok is False
    assert any("sys" in v.reason for v in result.violations)


def test_import_from_always_rejected() -> None:
    source = "from math import sqrt\ndef f(s, p):\n    return sqrt(1.0)\n"
    result = validate(source)
    assert result.ok is False
    assert any("ImportFrom" in v.node_type or "from-import" in v.reason for v in result.violations)


# ---------------------------------------------------------------------------
# Call whitelist
# ---------------------------------------------------------------------------


def test_all_allowed_callables_pass() -> None:
    for name in sorted(ALLOWED_CALLABLES):
        source = f"def f(s, p):\n    return {name}(s)\n"
        result = validate(source)
        assert result.ok is True, f"Call to '{name}' should be allowed but got: " + "; ".join(
            v.reason for v in result.violations
        )


def test_rejected_attr_names_in_calls_fail() -> None:
    for name in sorted(REJECTED_ATTR_NAMES):
        # Some of these (e.g. __class__) aren't typically called as plain functions
        # but the Name check should still fire.  Use a template that creates a Call.
        source = f"def f(s, p):\n    return {name}(s)\n"
        result = validate(source)
        assert result.ok is False, f"Call to '{name}' should be rejected"


def test_math_attribute_call_passes() -> None:
    source = "import math\ndef f(s, p):\n    return math.sqrt(float(s['x']))\n"
    result = validate(source)
    assert result.ok is True


def test_statistics_attribute_call_passes() -> None:
    source = "import statistics\ndef f(s, p):\n    return statistics.mean(p['window'])\n"
    result = validate(source)
    assert result.ok is True


def test_snapshot_get_method_passes() -> None:
    """snapshot.get(key, default) is a common safe idiom and must pass."""
    source = "def f(s, p):\n    return float(s.get('price', 0.0))\n"
    result = validate(source)
    assert result.ok is True


def test_window_append_passes() -> None:
    """list.append is a standard idiom used in pure mean-reversion logic."""
    source = "def f(s, p):\n    p['window'].append(float(s['price']))\n    return None\n"
    result = validate(source)
    assert result.ok is True


# ---------------------------------------------------------------------------
# Assign target rules
# ---------------------------------------------------------------------------


def test_name_assign_in_function_passes() -> None:
    source = "def f(s, p):\n    x = 1\n    y = x + 1\n    return y\n"
    result = validate(source)
    assert result.ok is True


def test_tuple_unpack_assign_passes() -> None:
    source = "def f(s, p):\n    a, b = 1, 2\n    return a + b\n"
    result = validate(source)
    assert result.ok is True


def test_attribute_assign_rejected() -> None:
    source = "def f(s, p):\n    s.x = 1\n    return None\n"
    result = validate(source)
    assert result.ok is False
    assert any("attribute target" in v.reason for v in result.violations)


def test_subscript_assign_rejected() -> None:
    source = "def f(s, p):\n    p['x'] = 1\n    return None\n"
    result = validate(source)
    assert result.ok is False
    assert any("subscript target" in v.reason for v in result.violations)


# ---------------------------------------------------------------------------
# Banned attribute / name access
# ---------------------------------------------------------------------------


def test_dunder_class_access_rejected() -> None:
    source = "def f(s, p):\n    return s.__class__\n"
    result = validate(source)
    assert result.ok is False
    assert any("__class__" in v.reason for v in result.violations)


def test_dunder_dict_access_rejected() -> None:
    source = "def f(s, p):\n    return f.__dict__\n"
    result = validate(source)
    assert result.ok is False


# ---------------------------------------------------------------------------
# Decorator rejection
# ---------------------------------------------------------------------------


def test_decorator_on_top_level_function_rejected() -> None:
    source = "def dec(fn):\n    return fn\n\n@dec\ndef f(s, p):\n    return None\n"
    result = validate(source)
    assert result.ok is False
    assert any("decorator" in v.reason for v in result.violations)


# ---------------------------------------------------------------------------
# Comprehension — banned call inside elt must still be caught
# ---------------------------------------------------------------------------


def test_comprehension_with_banned_call_rejected() -> None:
    source = "def f(s, p):\n    return [open(x) for x in p['paths']]\n"
    result = validate(source)
    assert result.ok is False
    assert any("open" in v.reason for v in result.violations)


def test_generator_in_statistics_call_passes() -> None:
    source = "import statistics\ndef f(s, p):\n    return statistics.mean(x for x in p['window'])\n"
    result = validate(source)
    assert result.ok is True


# ---------------------------------------------------------------------------
# ValidationResult contract
# ---------------------------------------------------------------------------


def test_validation_result_is_frozen() -> None:
    result = validate("def f(s, p):\n    return None\n")
    assert result.ok is True
    with pytest.raises((AttributeError, TypeError)):
        result.ok = False  # type: ignore[misc]


def test_violation_is_frozen() -> None:
    result = validate("import os\ndef f(s, p):\n    return None\n")
    assert result.ok is False
    v = result.violations[0]
    with pytest.raises((AttributeError, TypeError)):
        v.reason = "mutated"  # type: ignore[misc]


def test_violation_has_correct_line() -> None:
    source = "def f(s, p):\n    exec('x=1')\n    return None\n"
    result = validate(source)
    assert result.ok is False
    exec_violations = [v for v in result.violations if "exec" in v.reason]
    assert exec_violations, "Expected an exec violation"
    assert exec_violations[0].line == 2


def test_nested_function_rejected() -> None:
    """Nested FunctionDef must be rejected with a 'nested' violation reason."""
    source = (
        "def outer(s, p):\n"
        "    def inner(x):\n"
        "        return x\n"
        "    return float(s['price'])\n"
    )
    result = validate(source)
    assert result.ok is False, "Expected nested FunctionDef to fail validation"
    assert any("nested" in v.reason.lower() for v in result.violations), (
        "Expected a violation mentioning 'nested'; got: "
        + "; ".join(v.reason for v in result.violations)
    )


# ---------------------------------------------------------------------------
# f-string / Pass / is-None — new admitted nodes
# ---------------------------------------------------------------------------


def test_fstring_passes() -> None:
    """f-string formatting (JoinedStr/FormattedValue) must be allowed."""
    source = "def f(s, p):\n    label = f\"{s['id']}\"\n    return None\n"
    result = validate(source)
    assert result.ok is True, "f-string should be allowed; violations: " + "; ".join(
        v.reason for v in result.violations
    )


def test_pass_body_passes() -> None:
    """A function whose body is only 'pass' must be allowed."""
    source = "def f(s, p):\n    pass\n"
    result = validate(source)
    assert result.ok is True, "pass body should be allowed"


def test_is_none_passes() -> None:
    """'x is None' / 'x is not None' comparisons must be allowed."""
    source = (
        "def f(s, p):\n"
        "    x = s.get('v')\n"
        "    if x is None:\n"
        "        return None\n"
        "    return float(x)\n"
    )
    result = validate(source)
    assert result.ok is True, "is None check should be allowed"


def test_in_operator_passes() -> None:
    """'key in dict' membership test must be allowed."""
    source = "def f(s, p):\n    if 'window' not in p:\n        return None\n    return 1.0\n"
    result = validate(source)
    assert result.ok is True, "not-in membership check should be allowed"


# ---------------------------------------------------------------------------
# Explicit rejection of NamedExpr / Match / Starred
# ---------------------------------------------------------------------------


def test_walrus_rejected() -> None:
    source = (
        "def f(s, p):\n    if (x := float(s['price'])) > 0:\n        return x\n    return None\n"
    )
    result = validate(source)
    assert result.ok is False
    assert any("walrus" in v.reason.lower() for v in result.violations)


def test_starred_in_call_rejected() -> None:
    source = "def f(s, p):\n    vals = [1.0, 2.0]\n    return max(*vals)\n"
    result = validate(source)
    assert result.ok is False
    assert any("starred" in v.reason.lower() for v in result.violations)


def test_match_statement_rejected() -> None:
    source = (
        "def f(s, p):\n"
        "    match s.get('type'):\n"
        "        case 'a':\n"
        "            return 1.0\n"
        "        case _:\n"
        "            return None\n"
    )
    result = validate(source)
    assert result.ok is False
    assert any("match" in v.reason.lower() for v in result.violations)


# ---------------------------------------------------------------------------
# SyntaxError column normalisation (0-based)
# ---------------------------------------------------------------------------


def test_syntax_error_col_is_zero_based() -> None:
    """SyntaxError col must be 0-based (exc.offset - 1)."""
    result = validate("def f(:\n    pass\n")
    assert result.ok is False
    assert result.violations[0].node_type == "SyntaxError"
    # col must be >= 0 (normalised from 1-based offset)
    assert result.violations[0].col >= 0


# ---------------------------------------------------------------------------
# bool/str/list/dict/tuple no longer in ALLOWED_CALLABLES
# ---------------------------------------------------------------------------


def test_removed_coercers_rejected() -> None:
    """bool/str/list/dict/tuple calls should now be rejected."""
    for name in ("bool", "str", "list", "dict", "tuple"):
        source = f"def f(s, p):\n    return {name}(s)\n"
        result = validate(source)
        assert result.ok is False, f"Call to '{name}' should now be rejected"


# ---------------------------------------------------------------------------
# No duplicate violations from module-level non-assignment stmts
# ---------------------------------------------------------------------------


def test_no_duplicate_violation_for_module_level_assign() -> None:
    """Module-level Assign should produce exactly one violation, not two."""
    source = "X = 1\ndef f(s, p):\n    return None\n"
    result = validate(source)
    assert result.ok is False
    # Count violations whose reasons reference the module-level assign.
    assign_violations = [
        v
        for v in result.violations
        if "module" in v.reason.lower() and "assign" in v.reason.lower()
    ]
    assert len(assign_violations) == 1, (
        f"Expected exactly 1 module-level assign violation, got {len(assign_violations)}: "
        + "; ".join(v.reason for v in assign_violations)
    )

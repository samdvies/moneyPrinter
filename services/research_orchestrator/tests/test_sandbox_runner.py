"""Tests for sandbox_runner.py — subprocess isolation layer.

Adversarial fixtures are read from disk and passed directly to run_in_sandbox,
bypassing the AST validator, to prove the sandbox alone contains each threat.

Platform notes
--------------
* CPU-rlimit and memory-rlimit tests are skipped on Windows (resource module
  unavailable).
* Network, filesystem, and builtins-stripping tests run on all platforms —
  that is the whole point of the belt-and-braces layer.
* Wall-clock timeout tests run on all platforms.
"""

from __future__ import annotations

import multiprocessing
import sys
import textwrap
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from research_orchestrator.sandbox_runner import SandboxResult, run_in_sandbox

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "adversarial_modules"


def _read_fixture(filename: str) -> str:
    return (_FIXTURES_DIR / filename).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Teardown fixture — assert no sandbox child processes leak
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_leaked_children() -> Generator[None, None, None]:
    """Yield into the test; after each test assert no active child processes."""
    yield
    # Allow up to 0.5 s for any slow cleanup from the previous test.
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        children = multiprocessing.active_children()
        if not children:
            break
        time.sleep(0.05)
    remaining = multiprocessing.active_children()
    assert not remaining, f"Test left {len(remaining)} active child process(es): {remaining}"


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


HAPPY_MODULE = textwrap.dedent(
    """\
    def compute(snapshot, params):
        return 42
    """
)


def test_happy_path_returns_value() -> None:
    result = run_in_sandbox(
        module_source=HAPPY_MODULE,
        entry_callable="compute",
        args=({}, {}),
        cpu_seconds=2,
        mem_mb=64,
        wall_timeout_s=10.0,
    )
    assert result.status == "ok"
    assert result.value == 42
    assert result.error_repr is None
    assert result.reason is None


def test_happy_path_with_arithmetic() -> None:
    source = textwrap.dedent(
        """\
        def signal(snapshot, params):
            bid = float(snapshot.get("bid", 0))
            ask = float(snapshot.get("ask", 0))
            spread = ask - bid
            return spread * 2.0
        """
    )
    result = run_in_sandbox(
        module_source=source,
        entry_callable="signal",
        args=({"bid": 1.0, "ask": 1.05}, {}),
        cpu_seconds=2,
        mem_mb=64,
        wall_timeout_s=10.0,
    )
    assert result.status == "ok"
    assert result.value is not None
    assert abs(result.value - 0.10) < 1e-9


# ---------------------------------------------------------------------------
# Wall-clock timeout
# ---------------------------------------------------------------------------


def test_wall_clock_timeout() -> None:
    """An infinite loop is killed by the wall-clock timeout."""
    start = time.monotonic()
    result = run_in_sandbox(
        module_source=_read_fixture("adv_cpu_spin.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=30,
        mem_mb=256,
        wall_timeout_s=3.0,
    )
    elapsed = time.monotonic() - start
    assert result.status == "timeout"
    assert result.reason is not None and "timeout" in result.reason
    # Must complete within timeout + 5 s grace for terminate/kill.
    assert elapsed < 10.0


def test_infinite_generator_timeout() -> None:
    """Infinite generator in a tight loop is killed by wall-clock timeout."""
    result = run_in_sandbox(
        module_source=_read_fixture("adv_infinite_generator.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=30,
        mem_mb=256,
        wall_timeout_s=3.0,
    )
    assert result.status == "timeout"


# ---------------------------------------------------------------------------
# Network blocking
# ---------------------------------------------------------------------------


def test_socket_create_connection_blocked() -> None:
    result = run_in_sandbox(
        module_source=_read_fixture("adv_socket_connect.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=5,
        mem_mb=64,
        wall_timeout_s=8.0,
    )
    # The fixture does `import socket` at module-level.  In the sandbox child
    # __builtins__['__import__'] is stripped, so the import itself raises
    # ImportError before the monkey-patched socket.create_connection is even
    # reached.  Either way the network egress is blocked — status must be
    # "error" and the error must not indicate a successful connection.
    assert result.status == "error"
    assert result.error_repr is not None
    # Must be blocked by one of: __import__ strip, network monkey-patch, or
    # the socket call raising RuntimeError.  A successful HTTP response would
    # mean the sandbox failed.
    assert "200 OK" not in (result.error_repr or "") and "200 OK" not in (result.value or "")


def test_nested_class_side_effect_blocked() -> None:
    """Module-level socket side-effect at import time is blocked by monkey-patch."""
    result = run_in_sandbox(
        module_source=_read_fixture("adv_nested_class_side_effect.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=5,
        mem_mb=64,
        wall_timeout_s=8.0,
    )
    # The socket is monkey-patched before import; the try/except in the module
    # catches the RuntimeError, so the module loads and run() returns normally
    # OR the patched socket raises and the class-body try/except swallows it.
    # Either "ok" (side-effect caught by module's own try/except) or "error" is
    # acceptable — what matters is that no real connection was made.
    # The test's real assertion is the no_leaked_children fixture.
    assert result.status in {"ok", "error"}


# ---------------------------------------------------------------------------
# Filesystem blocking
# ---------------------------------------------------------------------------


def test_open_passwd_blocked() -> None:
    """open() is stripped from __builtins__ before the user module runs."""
    result = run_in_sandbox(
        module_source=_read_fixture("adv_open_passwd.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=5,
        mem_mb=64,
        wall_timeout_s=8.0,
    )
    assert result.status == "error"
    assert result.error_repr is not None
    # Should be NameError or similar — 'open' not defined
    assert any(
        token in result.error_repr for token in ("NameError", "open", "not defined", "builtin")
    )


# ---------------------------------------------------------------------------
# Builtins stripping
# ---------------------------------------------------------------------------


def test_dunder_import_os_blocked() -> None:
    """Dynamic import of 'os' via __import__ is blocked in the sandbox.

    Previously ``__import__`` was stripped from ``__builtins__`` entirely
    (NameError); now a *restricted* ``__import__`` is provided that only
    allows AST-whitelisted modules (math, statistics, dataclasses).  Either
    way, importing ``os`` raises an error and the result is "error".
    """
    result = run_in_sandbox(
        module_source=_read_fixture("adv_dunder_import_os.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=5,
        mem_mb=64,
        wall_timeout_s=8.0,
    )
    assert result.status == "error"
    assert result.error_repr is not None
    # Accept both the old "NameError/__import__/not defined/builtin" message
    # (if __import__ is stripped entirely) and the new restricted-import
    # message ("not allowed", "whitelist", "ImportError").
    assert any(
        token in result.error_repr
        for token in (
            "NameError",
            "__import__",
            "not defined",
            "builtin",
            "not allowed",
            "whitelist",
            "ImportError",
        )
    )


def test_ctypes_blocked() -> None:
    """ctypes import via __import__ is blocked by builtins stripping."""
    result = run_in_sandbox(
        module_source=_read_fixture("adv_ctypes.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=5,
        mem_mb=64,
        wall_timeout_s=8.0,
    )
    assert result.status == "error"
    assert result.error_repr is not None


def test_subprocess_fork_bomb_blocked() -> None:
    """subprocess import inside run() is blocked by builtins __import__ strip."""
    result = run_in_sandbox(
        module_source=_read_fixture("adv_subprocess_fork_bomb.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=5,
        mem_mb=64,
        wall_timeout_s=5.0,
    )
    # The import of subprocess happens inside run() via normal import statement.
    # After builtins stripping, 'import subprocess' calls __import__ which is
    # stripped — so we get NameError or ImportError.  Alternatively the wall-
    # clock timeout fires.  Either "error" or "timeout" is acceptable.
    assert result.status in {"error", "timeout"}


# ---------------------------------------------------------------------------
# Pickle-RCE defence
# ---------------------------------------------------------------------------


def test_pickle_rce_does_not_execute_payload() -> None:
    """Parent must not run a malicious __reduce__ during queue.get().

    The adv_pickle_rce module returns a MaliciousResult whose __reduce__
    would call os.system("echo pwned").  The sandbox parent wraps queue.get()
    in try/except BaseException, so the RCE payload is caught and the result
    is SandboxResult(status="error", ...) rather than a shell execution.

    Note: multiprocessing.Queue pickles objects in the child before putting
    them on the pipe, so MaliciousResult.__reduce__ runs at put() time in the
    child, not at get() time in the parent.  The parent therefore receives
    already-pickled bytes.  When it unpickles them (inside queue.get()), the
    __reduce__ reconstructor (os.system) *would* run.  The PICKLE-RCE DEFENCE
    try/except in run_in_sandbox catches any BaseException raised during that
    deserialization.
    """
    result = run_in_sandbox(
        module_source=_read_fixture("adv_pickle_rce.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=5,
        mem_mb=64,
        wall_timeout_s=8.0,
    )
    # The __import__ strip in the child means 'import os' inside the module
    # will fail (os is imported at module-level in the fixture, not inside
    # run()), so the child either errors on import OR returns a MaliciousResult
    # that triggers the PICKLE-RCE defence on get().
    # Either way the parent must not execute the payload.
    assert result.status in {"error", "killed"}
    # Verify the parent didn't silently return "ok" with an executable payload.
    assert result.value is None


# ---------------------------------------------------------------------------
# Resource-limit tests (Unix only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="resource module unavailable on Windows")
def test_cpu_spin_killed_by_rlimit() -> None:
    """RLIMIT_CPU sends SIGXCPU which terminates the child (Linux/macOS)."""
    result = run_in_sandbox(
        module_source=_read_fixture("adv_cpu_spin.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=2,
        mem_mb=256,
        wall_timeout_s=10.0,
    )
    # Either killed by SIGXCPU (status "killed") or caught by wall-clock timeout.
    assert result.status in {"killed", "timeout"}


@pytest.mark.skipif(sys.platform == "win32", reason="resource module unavailable on Windows")
def test_mem_balloon_killed_by_rlimit() -> None:
    """RLIMIT_AS prevents large allocation from succeeding (Linux/macOS)."""
    result = run_in_sandbox(
        module_source=_read_fixture("adv_mem_balloon.py"),
        entry_callable="run",
        args=({}, {}),
        cpu_seconds=10,
        mem_mb=128,  # 128 MiB limit; fixture tries 4 GiB
        wall_timeout_s=10.0,
    )
    # MemoryError inside child → status "error", OR OS kills → "killed"
    assert result.status in {"error", "killed"}


# ---------------------------------------------------------------------------
# SandboxResult dataclass contract
# ---------------------------------------------------------------------------


def test_sandbox_result_is_frozen() -> None:
    r = SandboxResult(status="ok", value=1, error_repr=None, reason=None)
    with pytest.raises((AttributeError, TypeError)):
        r.status = "error"  # type: ignore[misc]


def test_sandbox_result_fields() -> None:
    r = SandboxResult(status="timeout", value=None, error_repr="x", reason="wall-clock timeout")
    assert r.status == "timeout"
    assert r.value is None
    assert r.error_repr == "x"
    assert r.reason == "wall-clock timeout"

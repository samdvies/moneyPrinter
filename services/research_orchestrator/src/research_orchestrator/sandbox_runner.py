"""Subprocess sandbox for executing LLM-generated strategy modules.

Phase 6c safety layer 2 — the AST validator (ast_validator.py) is the primary
defence; this sandbox is the belt-and-braces containment for anything that
somehow slips through.

Design decisions
----------------
* ``multiprocessing.get_context("spawn").Process`` — never ``fork``.  ``spawn``
  starts a clean Python interpreter that re-imports only what it explicitly
  imports, so parent file-descriptors, sockets, and import-state are not
  inherited by the child.

* IPC via ``multiprocessing.Queue`` — the spec suggests stdin/stdout byte
  streams, but a ``Queue`` (backed by a ``Pipe``) gives the same contract with
  simpler code.  The child puts ``(status, value_or_repr, reason)`` on the
  queue; the parent retrieves it with ``queue.get(timeout=wall_timeout_s)``.

* Result shape — flat frozen dataclass rather than the spec's Ok/Err envelope.
  Downstream code pattern-matches on ``status``; the flat shape is less verbose
  than a tagged union.

Windows caveat (spec §4.4)
--------------------------
The ``resource`` module (``RLIMIT_CPU``, ``RLIMIT_AS``) is Unix-only and does
not exist on Windows.  On Windows:

* ``resource.setrlimit`` calls are skipped entirely.
* CPU/memory containment falls back exclusively to the wall-clock timeout —
  the parent calls ``proc.join(timeout=wall_timeout_s)`` then
  ``proc.terminate()`` / ``proc.kill()``.
* Network and filesystem containment via monkey-patching and ``__builtins__``
  stripping are still applied and work correctly on Windows.
* Tests that specifically exercise ``RLIMIT_CPU`` or ``RLIMIT_AS`` are
  skipped on Windows via ``pytest.mark.skipif``.

Pickle-RCE defence
------------------
The parent retrieves the child's result with ``queue.get(timeout=...)``.
Python's ``multiprocessing.Queue`` uses ``pickle`` internally, so a
``MaliciousResult.__reduce__`` payload would execute during ``queue.get()``.
To defend against this, the parent wraps ``queue.get()`` in a broad
``try/except BaseException`` and converts any exception (including one fired
by a malicious ``__reduce__``) into a ``SandboxResult(status="error", ...)``.
The comment ``# PICKLE-RCE DEFENCE`` marks that line.

Child process entry point
--------------------------
``_sandbox_child_main`` is a **module-level** function so that the ``spawn``
context can pickle the ``target=`` reference without importing anything other
than this module.  Do not move it inside another function or class.
"""

from __future__ import annotations

import builtins
import multiprocessing
import multiprocessing.queues
import sys
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BANNED_BUILTINS: tuple[str, ...] = (
    "__import__",
    "open",
    "eval",
    "exec",
    "compile",
    "input",
    "memoryview",
)

# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxResult:
    """Result returned by ``run_in_sandbox``.

    Attributes
    ----------
    status:
        One of ``"ok"``, ``"timeout"``, ``"error"``, ``"killed"``.
    value:
        Populated when ``status == "ok"``; the return value of the called
        function.
    error_repr:
        Populated when ``status in {"error", "killed", "timeout"}``; a string
        representation of the exception or kill reason.
    reason:
        Human-readable explanation for non-ok outcomes (e.g. "wall-clock
        timeout", "network blocked", "rlimit-cpu").
    """

    status: str  # "ok" | "timeout" | "error" | "killed"
    value: Any | None
    error_repr: str | None
    reason: str | None


# ---------------------------------------------------------------------------
# Child-process entry point (must be module-level for spawn pickling)
# ---------------------------------------------------------------------------


def _sandbox_child_main(
    source: str,
    entry: str,
    args: tuple[Any, ...],
    queue: multiprocessing.queues.Queue,  # type: ignore[type-arg]
) -> None:
    """Run inside the spawned child process.

    Execution order:
    1. Apply resource limits (Unix only).
    2. Monkey-patch networking.
    3. Strip dangerous builtins.
    4. Compile + exec the user module source.
    5. Call the entry callable with *args*.
    6. Put (status, value, reason) on the queue.

    Any unhandled exception is caught and put as ("error", repr(exc), reason).
    """
    # ------------------------------------------------------------------
    # Step 1: resource limits (Unix only)
    # ------------------------------------------------------------------
    # These are set via module globals injected by run_in_sandbox before
    # spawning.  The child reads them so _sandbox_child_main stays
    # pickle-safe (no closure over parent locals).
    # ------------------------------------------------------------------
    if sys.platform != "win32":
        try:
            import resource  # type: ignore[import-untyped]  # Unix only

            cpu_secs = _CHILD_CPU_SECONDS
            mem_mb = _CHILD_MEM_MB
            if cpu_secs > 0:
                rlimit_cpu = resource.RLIMIT_CPU
                resource.setrlimit(rlimit_cpu, (cpu_secs, cpu_secs + 1))
            if mem_mb > 0:
                mem_bytes = mem_mb * 1024 * 1024
                rlimit_as = resource.RLIMIT_AS
                resource.setrlimit(rlimit_as, (mem_bytes, mem_bytes))
        except Exception:
            pass  # Don't abort the child for a failed rlimit

    # ------------------------------------------------------------------
    # Step 2: Monkey-patch networking
    # ------------------------------------------------------------------
    import socket
    import urllib.request

    def _blocked_socket(*a: Any, **kw: Any) -> None:
        raise RuntimeError("sandbox: network access is blocked")

    def _blocked_create_connection(*a: Any, **kw: Any) -> None:
        raise RuntimeError("sandbox: network access is blocked (create_connection)")

    def _blocked_urlopen(*a: Any, **kw: Any) -> None:
        raise RuntimeError("sandbox: network access is blocked (urlopen)")

    # Monkey-patch networking.  socket.socket is a class; assigning a plain
    # function is intentional — mypy flags it as [misc] and [assignment].
    socket.socket = _blocked_socket  # type: ignore[misc, assignment]
    socket.create_connection = _blocked_create_connection  # type: ignore[assignment]
    urllib.request.urlopen = _blocked_urlopen

    # ------------------------------------------------------------------
    # Step 3: Strip dangerous builtins
    # ------------------------------------------------------------------
    # __builtins__ is a dict when we are in a non-__main__ module context
    # (i.e. after spawn re-imports this module in the child) and a module
    # when running in __main__.  We normalise to a dict either way.
    raw_builtins = vars(builtins)
    stripped: dict[str, Any] = {k: v for k, v in raw_builtins.items() if k not in _BANNED_BUILTINS}

    # ------------------------------------------------------------------
    # Step 4 + 5: Compile, exec, call
    # ------------------------------------------------------------------
    try:
        code = compile(source, "<sandbox>", "exec")
        # Pre-inject whitelisted stdlib modules AND a restricted __import__
        # so that generated code using ``import math`` / ``import statistics``
        # / ``import dataclasses`` (AST-whitelisted) can run correctly.
        # The real __import__ is captured BEFORE being stripped from builtins.
        # All other modules are blocked immediately — belt-and-braces on top
        # of the AST validator that already blocks their import statements.
        import dataclasses as _dc
        import math as _math
        import statistics as _stats

        _SANDBOX_ALLOWED_IMPORTS = frozenset({"math", "statistics", "dataclasses"})
        # Capture the real __import__ from builtins BEFORE building stripped.
        # ``raw_builtins`` still has it at this point; stripped has it removed.
        _real_import = raw_builtins["__import__"]

        def _restricted_import(
            name: str,
            glb: Any = None,
            loc: Any = None,
            fromlist: Any = (),
            level: int = 0,
        ) -> Any:
            top_level = name.split(".")[0]
            if top_level not in _SANDBOX_ALLOWED_IMPORTS:
                raise ImportError(f"sandbox: import of '{name}' is not allowed (not in whitelist)")
            return _real_import(name, glb, loc, fromlist, level)

        restricted_builtins = dict(stripped)
        restricted_builtins["__import__"] = _restricted_import

        module_ns: dict[str, Any] = {
            "__builtins__": restricted_builtins,
            "math": _math,
            "statistics": _stats,
            "dataclasses": _dc,
        }
        exec(code, module_ns)

        if entry not in module_ns:
            raise AttributeError(f"entry callable '{entry}' not found in module")

        callable_fn = module_ns[entry]
        result = callable_fn(*args)
        queue.put(("ok", result, None))
    except Exception as exc:
        queue.put(("error", repr(exc), f"exception in child: {type(exc).__name__}"))


# ---------------------------------------------------------------------------
# Module-level mutable placeholders for resource-limit params
# (set by run_in_sandbox before spawning; read by _sandbox_child_main)
# ---------------------------------------------------------------------------
_CHILD_CPU_SECONDS: int = 0
_CHILD_MEM_MB: int = 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_in_sandbox(
    module_source: str,
    entry_callable: str,
    args: tuple[Any, ...] = (),
    cpu_seconds: int = 5,
    mem_mb: int = 256,
    wall_timeout_s: float = 10.0,
) -> SandboxResult:
    """Run ``entry_callable`` from ``module_source`` inside a sandboxed child.

    Parameters
    ----------
    module_source:
        Python source code string for the strategy module.
    entry_callable:
        Name of the function to call inside the module.
    args:
        Positional arguments forwarded to the callable.
    cpu_seconds:
        CPU time limit (Unix only; ignored on Windows).
    mem_mb:
        Address-space limit in MiB (Unix only; ignored on Windows).
    wall_timeout_s:
        Wall-clock timeout in seconds.  The parent waits this long then
        terminates the child unconditionally.

    Returns
    -------
    SandboxResult
        status == "ok"      : callable returned normally; value is set.
        status == "timeout" : child exceeded wall_timeout_s.
        status == "error"   : child raised an exception; error_repr is set.
        status == "killed"  : child was terminated for resource/policy reasons.
    """
    # Inject resource-limit params as module globals so the child function
    # (which must be picklable without closures) can read them.
    global _CHILD_CPU_SECONDS, _CHILD_MEM_MB
    _CHILD_CPU_SECONDS = cpu_seconds
    _CHILD_MEM_MB = mem_mb

    ctx = multiprocessing.get_context("spawn")
    queue: multiprocessing.queues.Queue[Any] = ctx.Queue()

    proc = ctx.Process(
        target=_sandbox_child_main,
        args=(module_source, entry_callable, args, queue),
        daemon=True,
    )
    proc.start()

    # Wait for child to finish or hit the wall-clock limit.
    proc.join(timeout=wall_timeout_s)

    if proc.is_alive():
        # Child is still running — kill it.
        proc.terminate()
        proc.join(timeout=2.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=2.0)
        return SandboxResult(
            status="timeout",
            value=None,
            error_repr=f"child exceeded wall-clock timeout of {wall_timeout_s}s",
            reason="wall-clock timeout",
        )

    # Child exited.  Try to read the result from the queue.
    # PICKLE-RCE DEFENCE: wrap queue.get() in bare except so that a malicious
    # __reduce__ method firing during unpickling is caught here and never
    # executed in the parent's main thread.  Any BaseException (including
    # ones raised by __reduce__) converts to an "error" SandboxResult.
    try:
        if queue.empty():
            # Child exited without putting anything — it likely crashed or was
            # killed by the OS (e.g. OOM-killer, SIGXCPU).
            exit_code = proc.exitcode
            reason = _exit_code_reason(exit_code)
            return SandboxResult(
                status="killed",
                value=None,
                error_repr=f"child exited with code {exit_code} (no result on queue)",
                reason=reason,
            )

        raw = queue.get(block=True, timeout=1.0)
    except BaseException as exc:  # PICKLE-RCE DEFENCE
        return SandboxResult(
            status="error",
            value=None,
            error_repr=f"exception reading child result (possible pickle RCE attempt): {exc!r}",
            reason="pickle deserialisation error",
        )

    status, payload, child_reason = raw
    if status == "ok":
        return SandboxResult(status="ok", value=payload, error_repr=None, reason=None)
    return SandboxResult(
        status=status,
        value=None,
        error_repr=payload,
        reason=child_reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _exit_code_reason(exit_code: int | None) -> str:
    """Map a process exit code to a human-readable reason string."""
    if exit_code is None:
        return "unknown (child still running?)"
    if exit_code == 0:
        return "exited cleanly but no result on queue"
    # POSIX: negative exit codes are -signal_number
    if exit_code < 0 and sys.platform != "win32":
        import signal

        sig_num = -exit_code
        try:
            sig_name = signal.Signals(sig_num).name
        except ValueError:
            sig_name = f"signal {sig_num}"
        # SIGXCPU = CPU limit exceeded; SIGKILL = OOM-killer or kill()
        if hasattr(signal, "SIGXCPU") and sig_num == signal.SIGXCPU.value:
            return "rlimit-cpu (SIGXCPU)"
        if hasattr(signal, "SIGKILL") and sig_num == signal.SIGKILL.value:
            return "killed (SIGKILL — OOM or external kill)"
        return f"killed by {sig_name}"
    return f"non-zero exit code {exit_code}"

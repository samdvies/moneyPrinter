"""Strict AST whitelist validator for LLM-generated strategy code.

Phase 6c safety floor: every module emitted by the Grok codegen call passes
through this validator before it is imported or backtested.  Validation is
purely structural — no execution, no imports.

Design decision (Option C): the whitelist is calibrated for the pure
``(snapshot, params) -> signal | None`` function style that Grok is asked to
generate.  The hand-written reference strategy
``backtest_engine/strategies/mean_reversion.py`` contains production plumbing
(``ImportFrom`` from ``algobet_common``, module-level ``_FIXTURE_STRATEGY_ID``,
``del window[0:]``) that would require widening the attack surface.  Rather than
admit those nodes, the allowed-fixture for mean-reversion logic is a whitelist-
clean pure-function re-expression (``validator_allowed/allow_mean_reversion_pure.py``).
The production strategy is not touched; this validator never evaluates it.

Public API
----------
validate(source: str) -> ValidationResult
    Parse ``source`` and walk every AST node against the whitelist.
    Returns a frozen ``ValidationResult``.

ValidationResult
    ok: bool
    module: ast.Module | None    -- populated on success (and on failure, for
                                    inspection, if the source parsed at all)
    violations: tuple[Violation, ...]

Violation
    node_type: str
    line: int
    col: int
    reason: str
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Whitelist constants
# ---------------------------------------------------------------------------

ALLOWED_IMPORTS: frozenset[str] = frozenset({"math", "statistics", "dataclasses"})

# Every AST node class name that is unconditionally permitted to appear in the
# tree.  Nodes NOT in this set cause a violation unless handled by a special
# rule below (e.g. Import of a whitelisted module).
ALLOWED_NODES: frozenset[str] = frozenset(
    {
        # Module wrapper
        "Module",
        # Statement nodes
        "Expr",
        "FunctionDef",
        "Return",
        "If",
        # For/range/enumerate/zip admitted beyond spec §4.3 — needed for idiomatic
        # window iteration; revisit if strategy surface allows pure statistics-based
        # formulations without explicit loops.
        "For",
        "Assign",
        "AugAssign",
        "Pass",
        # Expression nodes
        "IfExp",
        "BoolOp",
        "BinOp",
        "UnaryOp",
        "Compare",
        "Call",
        "Name",
        "Constant",
        "Attribute",
        "Tuple",
        "List",
        "Dict",
        "Subscript",
        "Slice",
        # f-string nodes — admitted; Grok emits them routinely for diagnostic
        # strings; content is plain string formatting with no dynamic execution risk.
        "JoinedStr",
        "FormattedValue",
        "FormatSpec",
        # Comprehension forms
        "ListComp",
        "GeneratorExp",
        "DictComp",
        "SetComp",
        "comprehension",
        # Context sentinels (not real runtime objects)
        "Load",
        "Store",
        "Del",
        # Boolean operators
        "And",
        "Or",
        # Unary operators
        "Not",
        "USub",
        "UAdd",
        # Binary / augmented-assign operators
        "Add",
        "Sub",
        "Mult",
        "Div",
        "Mod",
        "FloorDiv",
        "Pow",
        # Comparison operators
        "Eq",
        "NotEq",
        "Lt",
        "LtE",
        "Gt",
        "GtE",
        "Is",
        "IsNot",
        "In",
        "NotIn",
        # arguments / arg
        "arguments",
        "arg",
    }
)

# Built-in names that may appear as the direct (non-attribute) target of a Call.
ALLOWED_CALLABLES: frozenset[str] = frozenset(
    {
        "abs",
        "min",
        "max",
        "sum",
        "len",
        "round",
        "sorted",
        "float",
        "int",
        # bool/str/list/dict/tuple coercers removed: pure strategies only need
        # float/int for numeric coercion; the collection/string coercers widen
        # the surface without a clear need.
        "range",
        "enumerate",
        "zip",
    }
)

# Attribute names (and bare Name ids) that are banned wherever they appear in
# the tree — as an attribute access leaf or as the function being called.
REJECTED_ATTR_NAMES: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "__import__",
        "compile",
        "open",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "input",
        "print",
        "__subclasses__",
        "__mro__",
        "__class__",
        "__bases__",
        "__builtins__",
        "__globals__",
        "__code__",
        "__dict__",
    }
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    node_type: str
    line: int
    col: int
    reason: str


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    module: ast.Module | None
    violations: tuple[Violation, ...]


# ---------------------------------------------------------------------------
# Validator implementation
# ---------------------------------------------------------------------------


def validate(source: str) -> ValidationResult:
    """Parse ``source`` and validate it against the AST whitelist.

    Returns ``ValidationResult(ok=True, module=..., violations=())`` when the
    source is clean, or ``ValidationResult(ok=False, ...)`` with one or more
    ``Violation`` entries describing every rejected node.
    """
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        # exc.offset is 1-based; normalise to 0-based col_offset convention.
        col = max((exc.offset or 1) - 1, 0)
        v = Violation(
            node_type="SyntaxError",
            line=exc.lineno or 0,
            col=col,
            reason=str(exc),
        )
        return ValidationResult(ok=False, module=None, violations=(v,))

    walker = _WhitelistWalker()
    walker.visit(tree)

    if walker.violations:
        return ValidationResult(
            ok=False,
            module=tree,
            violations=tuple(walker.violations),
        )
    return ValidationResult(ok=True, module=tree, violations=())


# ---------------------------------------------------------------------------
# Internal walker
# ---------------------------------------------------------------------------


class _WhitelistWalker(ast.NodeVisitor):
    """Walk every node and accumulate violations."""

    def __init__(self) -> None:
        self.violations: list[Violation] = []
        # Tracks whether we are currently inside a FunctionDef body (depth > 0).
        self._func_depth: int = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _violation(self, node: ast.AST, reason: str) -> None:
        line = getattr(node, "lineno", 0)
        col = getattr(node, "col_offset", 0)
        self.violations.append(
            Violation(
                node_type=type(node).__name__,
                line=line,
                col=col,
                reason=reason,
            )
        )

    def _node_name(self, node: ast.AST) -> str:
        return type(node).__name__

    # ------------------------------------------------------------------
    # Module-level structure
    # ------------------------------------------------------------------

    def visit_Module(self, node: ast.Module) -> None:
        """Enforce top-level structure: docstring? imports* functiondefs+.

        Statements rejected here are NOT further recursed into by generic_visit
        (we skip them) to avoid double-reporting their child nodes.  Allowed
        statements are walked normally.
        """
        allowed_stmts: list[ast.stmt] = []
        for i, stmt in enumerate(node.body):
            if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                # Optional leading docstring — allowed; walk it.
                allowed_stmts.append(stmt)
            elif isinstance(stmt, ast.Import):
                # Whitelisted imports only — validated in visit_Import
                allowed_stmts.append(stmt)
            elif isinstance(stmt, ast.FunctionDef):
                # Allowed — validated in visit_FunctionDef
                allowed_stmts.append(stmt)
            else:
                self._violation(
                    stmt,
                    f"module-level statement not allowed: {self._node_name(stmt)}",
                )
                # Do NOT recurse into the rejected subtree — its children would
                # generate secondary/duplicate violations (e.g. the Assign's
                # child Name/Constant would fire generic_visit checks again).
        for stmt in allowed_stmts:
            self.visit(stmt)

    # ------------------------------------------------------------------
    # Import nodes
    # ------------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            module = alias.name.split(".")[0]
            if module not in ALLOWED_IMPORTS:
                self._violation(
                    node,
                    f"import of non-whitelisted module '{alias.name}'",
                )
        # Do NOT recurse into Import children (there are none of interest)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._violation(node, "from-import (ImportFrom) is not allowed")

    # ------------------------------------------------------------------
    # Outright-banned statement types
    # ------------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._violation(node, "ClassDef is not allowed")
        # Do NOT recurse — body would generate spurious secondary violations

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._violation(node, "AsyncFunctionDef is not allowed")

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._violation(node, "AsyncFor is not allowed")

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._violation(node, "AsyncWith is not allowed")

    def visit_Await(self, node: ast.Await) -> None:
        self._violation(node, "Await is not allowed")

    def visit_Global(self, node: ast.Global) -> None:
        self._violation(node, "global statement is not allowed")

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._violation(node, "nonlocal statement is not allowed")

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._violation(node, "Lambda is not allowed")

    def visit_Try(self, node: ast.Try) -> None:
        self._violation(node, "Try/except is not allowed")

    # Python 3.11+ ExceptionGroup try*
    def visit_TryStar(self, node: ast.AST) -> None:
        self._violation(node, "TryStar is not allowed")

    def visit_With(self, node: ast.With) -> None:
        self._violation(node, "with statement is not allowed")

    def visit_Raise(self, node: ast.Raise) -> None:
        self._violation(node, "raise statement is not allowed")

    def visit_Delete(self, node: ast.Delete) -> None:
        self._violation(node, "delete statement is not allowed")

    def visit_Assert(self, node: ast.Assert) -> None:
        self._violation(node, "assert statement is not allowed")

    def visit_Yield(self, node: ast.Yield) -> None:
        self._violation(node, "yield is not allowed")

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self._violation(node, "yield from is not allowed")

    # Walrus operator (:=) — explicit rejection for clear violation message
    def visit_NamedExpr(self, node: ast.AST) -> None:
        self._violation(node, "NamedExpr (walrus :=) is not allowed")

    # Python 3.10+ match statement — explicit rejection for clear message
    def visit_Match(self, node: ast.AST) -> None:
        self._violation(node, "match statement is not allowed")

    def visit_MatchCase(self, node: ast.AST) -> None:
        self._violation(node, "match statement is not allowed")

    # Starred (*args / *collection) prevents unpacking tricks
    def visit_Starred(self, node: ast.AST) -> None:
        self._violation(node, "Starred (*args / *collection) is not allowed")

    # ------------------------------------------------------------------
    # FunctionDef — check decorator_list, then recurse
    # ------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.decorator_list:
            self._violation(node, "decorators on FunctionDef are not allowed")
        if self._func_depth > 0:
            # Nested function definition — pure-function style allows only one
            # top-level strategy function.
            self._violation(
                node,
                f"nested FunctionDef '{node.name}' is not allowed; "
                "only top-level strategy functions are permitted",
            )
            # Do NOT recurse into the nested def body to avoid cascading noise.
            return
        self._func_depth += 1
        self.generic_visit(node)
        self._func_depth -= 1

    # ------------------------------------------------------------------
    # Assign / AugAssign — target restrictions
    # ------------------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        # Module-level assigns are already rejected (and NOT recursed into) by
        # visit_Module, so if we reach here from a non-module context we are
        # definitely inside a function.  No double-reporting needed.
        for target in node.targets:
            self._check_assign_target(target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check_assign_target(node.target)
        self.generic_visit(node)

    def _check_assign_target(self, target: ast.expr) -> None:
        """Target must be Name or Tuple/List of Names (unpacking)."""
        if isinstance(target, ast.Name):
            return  # OK
        if isinstance(target, ast.Tuple | ast.List):
            for elt in target.elts:
                self._check_assign_target(elt)
            return
        if isinstance(target, ast.Attribute):
            self._violation(target, "assignment to attribute target (obj.x = ...) is not allowed")
            return
        if isinstance(target, ast.Subscript):
            self._violation(target, "assignment to subscript target (d[k] = ...) is not allowed")
            return
        self._violation(target, f"assignment to unsupported target type {self._node_name(target)}")

    # ------------------------------------------------------------------
    # Call — whitelist function targets
    # ------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        # Direct name call: abs(x), float(x), …
        if isinstance(func, ast.Name):
            name = func.id
            if name in REJECTED_ATTR_NAMES:
                self._violation(node, f"call to banned function '{name}' is not allowed")
            elif name not in ALLOWED_CALLABLES:
                self._violation(node, f"call to non-whitelisted function '{name}' is not allowed")
            # else: allowed — recurse into args
        elif isinstance(func, ast.Attribute):
            # math.sqrt(x) / statistics.mean(x) / snapshot.get(…)
            # The visit_Attribute handler already checks banned attr names as
            # plain access.  Here we only need to confirm the method leaf is not
            # in REJECTED_ATTR_NAMES; all other attribute calls on local names
            # (snapshot.get, window.append, params.setdefault …) are permitted.
            if func.attr in REJECTED_ATTR_NAMES:
                self._violation(
                    node, f"call to banned attribute method '{func.attr}' is not allowed"
                )
        else:
            # Calling an arbitrary expression (e.g. a subscript, a lambda result)
            self._violation(node, "call to non-Name/non-Attribute expression is not allowed")

        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Attribute — check for banned leaf names
    # ------------------------------------------------------------------

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in REJECTED_ATTR_NAMES:
            self._violation(node, f"access to banned attribute '{node.attr}' is not allowed")
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Name — check for banned names used as values
    # ------------------------------------------------------------------

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and node.id in REJECTED_ATTR_NAMES:
            self._violation(node, f"reference to banned name '{node.id}' is not allowed")
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # General node check — catch anything not explicitly handled above
    # ------------------------------------------------------------------

    def generic_visit(self, node: ast.AST) -> None:
        node_name = self._node_name(node)
        if node_name not in ALLOWED_NODES:
            # Only emit a violation if no specific visit_* method already did
            # (specific visit methods do NOT call generic_visit by default
            # unless they explicitly do so — but we override generic_visit
            # to be the catch-all, and specific methods call it at the end).
            # Check: was a specific visitor already dispatched?
            method = "visit_" + node_name
            if not hasattr(self, method):
                self._violation(node, f"node type '{node_name}' is not in the allowed set")
        super().generic_visit(node)

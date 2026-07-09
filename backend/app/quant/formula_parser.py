"""
Safe formula expression parser for Rule Playground component formulas.

Uses Python's ast module to parse expressions into an AST, then walks the
tree to validate nodes — NO eval() is ever called.

Allowed expression nodes:
  - Constants (numbers only)
  - Names (must be in the provided variable vocabulary)
  - BinOp with: Add, Sub, Mult, Div, Pow, Mod
  - UnaryOp with: USub, UAdd
  - Call with function names in ALLOWED_FUNCTIONS

Allowed functions: AVG, SLOPE, PERCENTILE_RANK, ZSCORE (per Section 6).
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

# ── Allow-lists ───────────────────────────────────────────────────────────────

ALLOWED_FUNCTIONS: set[str] = {"AVG", "SLOPE", "PERCENTILE_RANK", "ZSCORE"}

_ALLOWED_BINOP = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
)
_ALLOWED_UNARYOP = (ast.USub, ast.UAdd)

# ── AST visitor ───────────────────────────────────────────────────────────────

class _FormulaVisitor(ast.NodeVisitor):
    """
    Walks the expression AST and collects:
      - referenced_vars: variable names used
      - bad_vars:        variable names not in vocabulary
      - bad_funcs:       function names not in ALLOWED_FUNCTIONS
      - bad_nodes:       node types that are not permitted
    """

    def __init__(self, available_variables: set[str]) -> None:
        self.available_variables = available_variables
        self.referenced_vars: set[str] = set()
        self.bad_vars: set[str] = set()
        self.bad_funcs: set[str] = set()
        self.bad_nodes: list[str] = []

    def visit_Name(self, node: ast.Name) -> None:
        self.referenced_vars.add(node.id)
        if node.id not in self.available_variables:
            self.bad_vars.add(node.id)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn not in ALLOWED_FUNCTIONS:
                self.bad_funcs.add(fn)
        else:
            # Attribute access, lambda, etc. — never allowed
            self.bad_nodes.append(type(node.func).__name__)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if not isinstance(node.op, _ALLOWED_BINOP):
            self.bad_nodes.append(type(node.op).__name__)
        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if not isinstance(node.op, _ALLOWED_UNARYOP):
            self.bad_nodes.append(type(node.op).__name__)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, (int, float)):
            self.bad_nodes.append(f"Constant({type(node.value).__name__})")

    # Block all other nodes that could be unsafe
    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.bad_nodes.append("Attribute access")

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.bad_nodes.append("Subscript")

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.bad_nodes.append("Lambda")

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.bad_nodes.append("IfExp (conditional)")

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self.bad_nodes.append("ListComp")

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self.bad_nodes.append("GeneratorExp")


# ── Safe expression evaluator (no eval) ──────────────────────────────────────

_BINOP_OPS = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.Pow:  operator.pow,
    ast.Mod:  operator.mod,
}
_UNARY_OPS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node: ast.AST, env: dict[str, float]) -> float:
    """
    Recursively evaluate a pre-validated AST node against a variable environment.
    No eval() is used — this is a manual tree-walking interpreter.
    """
    if isinstance(node, ast.Constant):
        return float(node.value)

    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"Variable '{node.id}' has no value in environment")
        return float(env[node.id])

    if isinstance(node, ast.BinOp):
        left  = _eval_node(node.left, env)
        right = _eval_node(node.right, env)
        op_fn = _BINOP_OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        if isinstance(node.op, ast.Div) and right == 0:
            raise ZeroDivisionError("Division by zero in formula")
        return op_fn(left, right)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, env)
        op_fn   = _UNARY_OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_fn(operand)

    if isinstance(node, ast.Call):
        fn_name = node.func.id  # type: ignore[attr-defined]
        args    = [_eval_node(a, env) for a in node.args]
        return _call_function(fn_name, args, env)

    raise ValueError(f"Unexpected AST node type: {type(node).__name__}")


def _call_function(name: str, args: list[float], env: dict[str, float]) -> float:
    """Evaluate an allowed function call."""
    if name == "AVG":
        if not args:
            raise ValueError("AVG() requires at least one argument")
        return sum(args) / len(args)

    if name == "SLOPE":
        # SLOPE(y_values...) — linear regression slope of the arguments (treated as equally-spaced)
        if len(args) < 2:
            raise ValueError("SLOPE() requires at least 2 arguments")
        n   = len(args)
        xs  = list(range(n))
        x_m = sum(xs) / n
        y_m = sum(args) / n
        num = sum((x - x_m) * (y - y_m) for x, y in zip(xs, args))
        den = sum((x - x_m) ** 2 for x in xs)
        if den == 0:
            return 0.0
        return num / den

    if name == "PERCENTILE_RANK":
        # PERCENTILE_RANK(value, v1, v2, ...) — pct rank of first arg within remaining
        if len(args) < 2:
            raise ValueError("PERCENTILE_RANK() requires at least 2 arguments")
        val, *universe = args
        rank = sum(1 for v in universe if v <= val)
        return rank / len(universe)

    if name == "ZSCORE":
        # ZSCORE(value, mean, std)
        if len(args) != 3:
            raise ValueError("ZSCORE() requires exactly 3 arguments: (value, mean, std)")
        val, mean, std = args
        if std == 0:
            return 0.0
        return (val - mean) / std

    raise ValueError(f"Unknown function: {name}")


# ── Public API ────────────────────────────────────────────────────────────────

class FormulaValidationResult:
    __slots__ = (
        "valid", "parsed_variables", "error_message",
        "error_type", "sample_preview",
    )

    def __init__(
        self,
        valid: bool,
        parsed_variables: list[str],
        error_message: str | None,
        error_type: str | None,
        sample_preview: list[dict[str, Any]] | None,
    ) -> None:
        self.valid            = valid
        self.parsed_variables = parsed_variables
        self.error_message    = error_message
        self.error_type       = error_type
        self.sample_preview   = sample_preview

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid":             self.valid,
            "parsed_variables":  self.parsed_variables,
            "error_message":     self.error_message,
            "error_type":        self.error_type,
            "sample_preview":    self.sample_preview,
        }


def validate_formula(
    formula_text: str,
    available_variables: list[str],
    sample_envs: list[dict[str, float]] | None = None,
) -> FormulaValidationResult:
    """
    Validate a formula expression string.

    Args:
        formula_text:        The expression string, e.g. "information_ratio_3yr * 0.4 + sharpe_ratio_3yr * 0.6"
        available_variables: List of allowed variable names (from the metric vocabulary).
        sample_envs:         Optional list of up to 3 dicts mapping variable names to float values.
                             Used to compute sample_preview without eval().

    Returns:
        FormulaValidationResult with:
          valid, parsed_variables, error_message, error_type, sample_preview
    """
    vocab = set(available_variables)
    formula_text = formula_text.strip()

    if not formula_text:
        return FormulaValidationResult(
            valid=False,
            parsed_variables=[],
            error_message="Formula is empty",
            error_type="empty",
            sample_preview=None,
        )

    # Parse into AST
    try:
        tree = ast.parse(formula_text, mode="eval")
    except SyntaxError as exc:
        return FormulaValidationResult(
            valid=False,
            parsed_variables=[],
            error_message=f"Syntax error: {exc.msg} (line {exc.lineno}, col {exc.offset})",
            error_type="syntax",
            sample_preview=None,
        )

    # Walk and validate
    visitor = _FormulaVisitor(vocab)
    visitor.visit(tree.body)

    if visitor.bad_nodes:
        return FormulaValidationResult(
            valid=False,
            parsed_variables=sorted(visitor.referenced_vars),
            error_message=f"Formula uses disallowed constructs: {', '.join(visitor.bad_nodes)}. "
                          "Only arithmetic operators (+, -, *, /, **), numbers, variables, "
                          "and the functions AVG/SLOPE/PERCENTILE_RANK/ZSCORE are permitted.",
            error_type="disallowed_construct",
            sample_preview=None,
        )

    if visitor.bad_funcs:
        return FormulaValidationResult(
            valid=False,
            parsed_variables=sorted(visitor.referenced_vars),
            error_message=f"Formula uses unsupported function(s): {', '.join(sorted(visitor.bad_funcs))}. "
                          f"Allowed: {', '.join(sorted(ALLOWED_FUNCTIONS))}.",
            error_type="invalid_function",
            sample_preview=None,
        )

    if visitor.bad_vars:
        return FormulaValidationResult(
            valid=False,
            parsed_variables=sorted(visitor.referenced_vars),
            error_message=f"Formula references unknown variable(s): {', '.join(sorted(visitor.bad_vars))}. "
                          f"Available: {', '.join(sorted(vocab))}.",
            error_type="invalid_variable",
            sample_preview=None,
        )

    # Formula is structurally valid — compute sample preview
    preview: list[dict[str, Any]] | None = None
    if sample_envs:
        preview = []
        for i, env in enumerate(sample_envs[:3]):
            try:
                value = _eval_node(tree.body, env)
                preview.append({
                    "fund_index": i + 1,
                    "inputs": {k: env[k] for k in sorted(visitor.referenced_vars) if k in env},
                    "result": round(value, 6),
                    "error": None,
                })
            except (ZeroDivisionError, ValueError, ArithmeticError) as exc:
                preview.append({
                    "fund_index": i + 1,
                    "inputs": {k: env[k] for k in sorted(visitor.referenced_vars) if k in env},
                    "result": None,
                    "error": str(exc),
                })

    return FormulaValidationResult(
        valid=True,
        parsed_variables=sorted(visitor.referenced_vars),
        error_message=None,
        error_type=None,
        sample_preview=preview,
    )

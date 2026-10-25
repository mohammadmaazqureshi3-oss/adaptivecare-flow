"""Evaluator for conditions: used by the Engine on live case data and by the Simulator."""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping
from typing import Any

from pathway_core.conditions.ast import BoolOp, Compare, Expr, InList, Literal, Name, Not, Value


class EvaluationError(ValueError):
    """Raised when a condition reads a value the case does not have."""


_CMP: dict[str, Callable[[Any, Any], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


def evaluate(expr: Expr, data: Mapping[str, Value]) -> Value:
    """Evaluate ``expr`` on ``data``. Raises ``EvaluationError`` for an unset variable."""
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, Name):
        if expr.id not in data:
            raise EvaluationError(f"variable {expr.id!r} is not set")
        return data[expr.id]
    if isinstance(expr, Not):
        return not evaluate(expr.operand, data)
    if isinstance(expr, BoolOp):
        return _bool_op(expr, data)
    if isinstance(expr, Compare):
        return _CMP[expr.op](evaluate(expr.left, data), evaluate(expr.right, data))
    if isinstance(expr, InList):
        value = evaluate(expr.value, data)
        return any(value == item.value for item in expr.items)
    raise TypeError(f"unknown expression {expr!r}")


def _bool_op(expr: BoolOp, data: Mapping[str, Value]) -> bool:
    # Short-circuit, like Python: the right side is read only when needed.
    left = bool(evaluate(expr.left, data))
    if expr.op == "or":
        return left or bool(evaluate(expr.right, data))
    return left and bool(evaluate(expr.right, data))

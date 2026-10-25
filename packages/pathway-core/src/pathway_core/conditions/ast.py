"""Syntax tree for conditions. The Verifier type-checks it; Engine and Simulator evaluate it."""

from __future__ import annotations

from dataclasses import dataclass

Value = int | float | str | bool


@dataclass(frozen=True)
class Literal:
    value: Value
    pos: int = 0


@dataclass(frozen=True)
class Name:
    id: str
    pos: int = 0


@dataclass(frozen=True)
class BoolOp:
    op: str  # "and" | "or"
    left: Expr
    right: Expr
    pos: int = 0


@dataclass(frozen=True)
class Not:
    operand: Expr
    pos: int = 0


@dataclass(frozen=True)
class Compare:
    op: str  # < <= > >= == !=
    left: Expr
    right: Expr
    pos: int = 0


@dataclass(frozen=True)
class InList:
    value: Expr
    items: tuple[Literal, ...]
    pos: int = 0


Expr = Literal | Name | BoolOp | Not | Compare | InList


def names(expr: Expr) -> set[str]:
    """Every variable a condition reads (used by the data-flow check)."""
    if isinstance(expr, Name):
        return {expr.id}
    if isinstance(expr, BoolOp | Compare):
        return names(expr.left) | names(expr.right)
    if isinstance(expr, Not):
        return names(expr.operand)
    if isinstance(expr, InList):
        return names(expr.value)
    return set()

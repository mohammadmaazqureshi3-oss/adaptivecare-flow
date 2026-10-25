"""Type checker for conditions: run by the Verifier before Publish.

Rules: every name must be a declared variable; comparisons need compatible
types (numbers with numbers, strings with strings, booleans with booleans and
only ``==``/``!=``); ``and``, ``or`` and ``not`` need booleans; the whole
condition must be boolean.
"""

from __future__ import annotations

from dataclasses import dataclass

from pathway_core.conditions.ast import BoolOp, Compare, Expr, InList, Literal, Name, Not

NUMERIC = frozenset({"int", "float"})


@dataclass(frozen=True)
class TypeIssue:
    message: str
    pos: int


def typecheck(expr: Expr, var_types: dict[str, str]) -> list[TypeIssue]:
    issues: list[TypeIssue] = []
    result = _type_of(expr, var_types, issues)
    if result is not None and result != "bool":
        issues.append(TypeIssue(f"condition must be true or false, not {result}", 0))
    return issues


def _literal_type(lit: Literal) -> str:
    if isinstance(lit.value, bool):
        return "bool"
    if isinstance(lit.value, int):
        return "int"
    if isinstance(lit.value, float):
        return "float"
    return "string"


def _compatible(a: str, b: str) -> bool:
    return a == b or (a in NUMERIC and b in NUMERIC)


def _type_of(e: Expr, env: dict[str, str], issues: list[TypeIssue]) -> str | None:
    """Return the type of ``e``, or ``None`` if it is already wrong (to avoid cascades)."""
    if isinstance(e, Literal):
        return _literal_type(e)
    if isinstance(e, Name):
        if e.id not in env:
            issues.append(TypeIssue(f"unknown variable {e.id!r}", e.pos))
            return None
        return env[e.id]
    if isinstance(e, Not):
        _expect_bool(e.operand, "'not'", e.pos, env, issues)
    elif isinstance(e, BoolOp):
        for side in (e.left, e.right):
            _expect_bool(side, f"'{e.op}'", e.pos, env, issues)
    elif isinstance(e, Compare):
        _check_compare(e, env, issues)
    elif isinstance(e, InList):
        _check_in_list(e, env, issues)
    return "bool"


def _expect_bool(e: Expr, what: str, pos: int, env: dict[str, str], issues: list[TypeIssue]) -> None:
    t = _type_of(e, env, issues)
    if t is not None and t != "bool":
        issues.append(TypeIssue(f"{what} needs true or false, not {t}", pos))


def _check_compare(e: Compare, env: dict[str, str], issues: list[TypeIssue]) -> None:
    lt, rt = _type_of(e.left, env, issues), _type_of(e.right, env, issues)
    if lt is None or rt is None:
        return
    if not _compatible(lt, rt):
        issues.append(TypeIssue(f"cannot compare {lt} with {rt}", e.pos))
    elif e.op not in ("==", "!=") and lt not in NUMERIC:
        issues.append(TypeIssue(f"'{e.op}' needs numbers, not {lt}", e.pos))


def _check_in_list(e: InList, env: dict[str, str], issues: list[TypeIssue]) -> None:
    vt = _type_of(e.value, env, issues)
    if vt is None:
        return
    for item in e.items:
        if not _compatible(vt, _literal_type(item)):
            issues.append(TypeIssue(f"list item {item.value!r} is not {vt}", item.pos))

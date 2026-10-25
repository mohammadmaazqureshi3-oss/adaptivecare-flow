"""Condition language: partition and boundary tests for lexer, parser, type checker, evaluator."""

from __future__ import annotations

import pytest
from pathway_core.conditions import (
    ConditionSyntaxError,
    EvaluationError,
    evaluate,
    names,
    parse,
    tokenize,
    typecheck,
)
from pathway_core.conditions.ast import BoolOp, Compare, InList, Literal, Name, Not

ENV = {"urgency": "int", "spo2": "int", "confidence": "float", "ward": "string", "conscious": "bool"}
TRIAGE = "urgency <= 2 or spo2 < 90 or confidence < 0.7"


# ---- lexer ------------------------------------------------------------------


def test_lexer_kinds() -> None:
    kinds = [t.kind for t in tokenize("not x >= 1.5 and w in ['a', \"b\"]")]
    assert kinds == [
        "not",
        "IDENT",
        ">=",
        "NUMBER",
        "and",
        "IDENT",
        "in",
        "[",
        "STRING",
        ",",
        "STRING",
        "]",
        "EOF",
    ]


@pytest.mark.parametrize("src,pos", [("a $ b", 2), ("'open", 0), ("1.2.3", 0)])
def test_lexer_errors_carry_the_position(src: str, pos: int) -> None:
    with pytest.raises(ConditionSyntaxError) as exc:
        tokenize(src)
    assert exc.value.pos == pos


# ---- parser -----------------------------------------------------------------


def test_precedence_or_binds_looser_than_and() -> None:
    tree = parse("a or b and c")
    assert isinstance(tree, BoolOp) and tree.op == "or"
    assert isinstance(tree.right, BoolOp) and tree.right.op == "and"


def test_parentheses_override_precedence() -> None:
    tree = parse("(a or b) and c")
    assert isinstance(tree, BoolOp) and tree.op == "and"


def test_not_and_in_list() -> None:
    tree = parse("not ward in ['A', 'B']")
    assert isinstance(tree, Not) and isinstance(tree.operand, InList)
    assert [i.value for i in tree.operand.items] == ["A", "B"]


def test_literals() -> None:
    assert parse("3") == Literal(3, 0)
    assert parse("0.7").value == 0.7  # type: ignore[union-attr]
    assert parse("true") == Literal(True, 0)
    assert parse("x") == Name("x", 0)
    assert isinstance(parse("x != 'a'"), Compare)


@pytest.mark.parametrize(
    "src", ["", "urgency <=", "urgency < < 2", "(urgency < 2", "urgency in []", "urgency in [1,]", "a b"]
)
def test_syntax_errors(src: str) -> None:
    with pytest.raises(ConditionSyntaxError):
        parse(src)


def test_names() -> None:
    assert names(parse(TRIAGE)) == {"urgency", "spo2", "confidence"}


# ---- type checker -------------------------------------------------------------


def test_triage_condition_type_checks() -> None:
    assert typecheck(parse(TRIAGE), ENV) == []


@pytest.mark.parametrize(
    "src,fragment",
    [
        ("pulse > 3", "unknown variable"),
        ("ward < 3", "cannot compare"),
        ("ward < 'B'", "needs numbers"),
        ("urgency and conscious", "'and' needs"),
        ("not urgency", "'not' needs"),
        ("urgency", "must be true or false"),
        ("urgency in [1, 'x']", "is not int"),
        ("conscious == 1", "cannot compare"),
    ],
)
def test_type_errors(src: str, fragment: str) -> None:
    issues = typecheck(parse(src), ENV)
    assert any(fragment in i.message for i in issues), issues


def test_int_and_float_are_compatible() -> None:
    assert typecheck(parse("confidence < 1 and urgency == 2.0"), ENV) == []


def test_bool_variable_is_a_condition() -> None:
    assert typecheck(parse("conscious and not conscious == false"), ENV) == []


# ---- evaluator ----------------------------------------------------------------


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"urgency": 2, "spo2": 98, "confidence": 0.9}, True),  # boundary: urgency == 2
        ({"urgency": 3, "spo2": 98, "confidence": 0.9}, False),  # just above
        ({"urgency": 3, "spo2": 89, "confidence": 0.9}, True),  # spo2 just below 90
        ({"urgency": 3, "spo2": 90, "confidence": 0.9}, False),  # spo2 == 90
        ({"urgency": 3, "spo2": 98, "confidence": 0.69}, True),
        ({"urgency": 3, "spo2": 98, "confidence": 0.7}, False),
    ],
)
def test_triage_condition_boundaries(data: dict, expected: bool) -> None:
    assert evaluate(parse(TRIAGE), data) is expected


def test_short_circuit_does_not_read_unneeded_values() -> None:
    assert evaluate(parse("urgency <= 2 or spo2 < 90"), {"urgency": 1}) is True


def test_missing_value_raises() -> None:
    with pytest.raises(EvaluationError):
        evaluate(parse("spo2 < 90"), {})


def test_in_list_and_not() -> None:
    assert evaluate(parse("ward in ['A', 'B']"), {"ward": "B"}) is True
    assert evaluate(parse("not ward in ['A', 'B']"), {"ward": "C"}) is True

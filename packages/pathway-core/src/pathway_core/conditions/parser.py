"""Recursive-descent parser for the condition language, one function per grammar rule.

expr     := and_expr { "or" and_expr }
and_expr := not_expr { "and" not_expr }
not_expr := "not" not_expr | cmp
cmp      := value [ ("<" | "<=" | ">" | ">=" | "==" | "!=") value ]
          | value "in" "[" literal { "," literal } "]"
value    := NUMBER | STRING | "true" | "false" | IDENT | "(" expr ")"
"""

from __future__ import annotations

from pathway_core.conditions.ast import BoolOp, Compare, Expr, InList, Literal, Name, Not
from pathway_core.conditions.lexer import ConditionSyntaxError, Token, tokenize

COMPARISONS = frozenset({"<", "<=", ">", ">=", "==", "!="})


def parse(source: str) -> Expr:
    """Parse ``source`` into a tree. Raises ``ConditionSyntaxError`` with a position."""
    return _Parser(tokenize(source)).parse()


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.i = 0

    # ---- helpers -----------------------------------------------------------

    @property
    def tok(self) -> Token:
        return self.tokens[self.i]

    def take(self, kind: str) -> Token:
        if self.tok.kind != kind:
            found = self.tok.text or "end of condition"
            raise ConditionSyntaxError(f"expected {kind!r} but found {found!r}", self.tok.pos)
        t = self.tok
        self.i += 1
        return t

    def accept(self, kind: str) -> Token | None:
        if self.tok.kind == kind:
            return self.take(kind)
        return None

    # ---- grammar rules -----------------------------------------------------

    def parse(self) -> Expr:
        if self.tok.kind == "EOF":
            raise ConditionSyntaxError("empty condition", 0)
        e = self.expr()
        self.take("EOF")
        return e

    def expr(self) -> Expr:
        left = self.and_expr()
        while op := self.accept("or"):
            left = BoolOp("or", left, self.and_expr(), op.pos)
        return left

    def and_expr(self) -> Expr:
        left = self.not_expr()
        while op := self.accept("and"):
            left = BoolOp("and", left, self.not_expr(), op.pos)
        return left

    def not_expr(self) -> Expr:
        if op := self.accept("not"):
            return Not(self.not_expr(), op.pos)
        return self.cmp()

    def cmp(self) -> Expr:
        left = self.value()
        if self.tok.kind in COMPARISONS:
            cmp_op = self.take(self.tok.kind)
            return Compare(cmp_op.kind, left, self.value(), cmp_op.pos)
        if op := self.accept("in"):
            self.take("[")
            items = [self.literal()]
            while self.accept(","):
                items.append(self.literal())
            self.take("]")
            return InList(left, tuple(items), op.pos)
        return left

    def value(self) -> Expr:
        t = self.tok
        if t.kind == "(":
            self.take("(")
            e = self.expr()
            self.take(")")
            return e
        if t.kind == "IDENT":
            self.take("IDENT")
            return Name(t.text, t.pos)
        return self.literal()

    def literal(self) -> Literal:
        t = self.tok
        if t.kind == "NUMBER":
            self.take("NUMBER")
            return Literal(float(t.text) if "." in t.text else int(t.text), t.pos)
        if t.kind == "STRING":
            self.take("STRING")
            return Literal(t.text, t.pos)
        if t.kind in ("true", "false"):
            self.take(t.kind)
            return Literal(t.kind == "true", t.pos)
        found = t.text or "end of condition"
        raise ConditionSyntaxError(f"expected a value but found {found!r}", t.pos)

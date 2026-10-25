"""Lexer for the condition language, e.g. ``urgency <= 2 or spo2 < 90``."""

from __future__ import annotations

from dataclasses import dataclass

KEYWORDS = frozenset({"and", "or", "not", "in", "true", "false"})
OPERATORS = ("<=", ">=", "==", "!=", "<", ">", "(", ")", "[", "]", ",")


class ConditionSyntaxError(ValueError):
    """A syntax error, with the character position the editor underlines."""

    def __init__(self, message: str, pos: int) -> None:
        super().__init__(f"{message} at position {pos}")
        self.message = message
        self.pos = pos


@dataclass(frozen=True)
class Token:
    kind: str  # NUMBER, STRING, IDENT, a keyword, an operator, or EOF
    text: str
    pos: int


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit() or (ch == "." and source[i + 1 : i + 2].isdigit()):
            tok, i = _number(source, i)
        elif ch.isalpha() or ch == "_":
            tok, i = _word(source, i)
        elif ch in "'\"":
            tok, i = _string(source, i)
        else:
            tok, i = _operator(source, i)
        tokens.append(tok)
    tokens.append(Token("EOF", "", n))
    return tokens


def _number(source: str, i: int) -> tuple[Token, int]:
    j = i
    while j < len(source) and (source[j].isdigit() or source[j] == "."):
        j += 1
    text = source[i:j]
    if text.count(".") > 1:
        raise ConditionSyntaxError(f"bad number {text!r}", i)
    return Token("NUMBER", text, i), j


def _word(source: str, i: int) -> tuple[Token, int]:
    j = i
    while j < len(source) and (source[j].isalnum() or source[j] == "_"):
        j += 1
    word = source[i:j]
    return Token(word if word in KEYWORDS else "IDENT", word, i), j


def _string(source: str, i: int) -> tuple[Token, int]:
    j = source.find(source[i], i + 1)
    if j < 0:
        raise ConditionSyntaxError("unterminated string", i)
    return Token("STRING", source[i + 1 : j], i), j + 1


def _operator(source: str, i: int) -> tuple[Token, int]:
    op = next((o for o in OPERATORS if source.startswith(o, i)), None)
    if op is None:
        raise ConditionSyntaxError(f"unexpected character {source[i]!r}", i)
    return Token(op, op, i), i + len(op)

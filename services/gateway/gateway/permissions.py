"""The permission matrix (plan Section 10) as routing rules. NFR-SEC-02, AUTH-03.

Every route a user can reach is listed here with the service behind it and the
roles allowed. Anything not listed is refused (deny by default).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PUBLIC = frozenset({"*public*"})  # no token needed
ANY_ROLE = frozenset({"admin", "designer", "nurse", "doctor", "manager"})

ADMIN = frozenset({"admin"})
DESIGNER = frozenset({"designer"})
# Managers read pathways to plan staffing; admins read published versions to deploy them (Sprint 4).
PATHWAY_READERS = frozenset({"designer", "manager", "admin"})


@dataclass(frozen=True)
class Rule:
    method: str
    path: str  # with {placeholders}
    service: str
    roles: frozenset[str]

    @property
    def regex(self) -> re.Pattern[str]:
        return re.compile("^" + re.sub(r"\{[a-z_]+\}", r"[^/]+", self.path) + "$")


RULES: tuple[Rule, ...] = (
    # auth
    Rule("POST", "/auth/login", "auth", PUBLIC),
    Rule("POST", "/auth/refresh", "auth", PUBLIC),
    Rule("GET", "/auth/me", "auth", ANY_ROLE),
    Rule("GET", "/users", "auth", ADMIN),
    Rule("POST", "/users", "auth", ADMIN),
    Rule("PATCH", "/users/{id}", "auth", ADMIN),
    # designer: pathways and versions
    Rule("GET", "/pathways", "designer", PATHWAY_READERS),
    Rule("POST", "/pathways", "designer", DESIGNER),
    Rule("GET", "/pathways/{id}", "designer", PATHWAY_READERS),
    Rule("PATCH", "/pathways/{id}", "designer", DESIGNER),
    Rule("GET", "/pathways/{id}/versions", "designer", PATHWAY_READERS),
    Rule("POST", "/pathways/{id}/versions", "designer", DESIGNER),
    Rule("GET", "/versions/{id}", "designer", PATHWAY_READERS),
    Rule("PUT", "/versions/{id}", "designer", DESIGNER),
    Rule("POST", "/versions/{id}/verify", "designer", DESIGNER),
    Rule("POST", "/versions/{id}/publish", "designer", DESIGNER),
    Rule("POST", "/conditions/check", "designer", DESIGNER),
)

_COMPILED = [(r, r.regex) for r in RULES]


def match(method: str, path: str) -> Rule | None:
    for rule, rx in _COMPILED:
        if rule.method == method and rx.match(path):
            return rule
    return None

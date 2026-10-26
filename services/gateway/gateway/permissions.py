"""The permission matrix (plan Section 10) as routing rules. NFR-SEC-02, AUTH-03.

Every route a user can reach is listed here with the service behind it and the
roles allowed. Anything not listed is refused (deny by default).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PUBLIC = frozenset({"*public*"})  # no token needed
ANY_ROLE = frozenset({"admin", "designer", "nurse", "charge_nurse", "doctor", "manager"})

ADMIN = frozenset({"admin"})
DESIGNER = frozenset({"designer"})
# Managers read pathways to plan staffing; admins read published versions to deploy them (Sprint 4).
PATHWAY_READERS = frozenset({"designer", "manager", "admin"})
# Charge nurses have a nurse's permissions and receive escalated tasks (decision 0004).
CLINICAL = frozenset({"nurse", "charge_nurse", "doctor"})
# "View cases and their history": admin, doctor, manager. "Dashboards and alerts": admin, manager.
CASE_READERS = frozenset({"admin", "doctor", "manager"})
MANAGERS = frozenset({"manager", "admin"})


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
    # simulator: designers and managers run and view simulations (SIM-01..03)
    Rule("POST", "/versions/{id}/simulations", "simulator", frozenset({"designer", "manager"})),
    Rule("GET", "/simulations", "simulator", frozenset({"designer", "manager"})),
    Rule("GET", "/simulations/compare", "simulator", frozenset({"designer", "manager"})),  # SIM-05
    Rule("GET", "/simulations/{id}", "simulator", frozenset({"designer", "manager"})),
    # deployer: only admins deploy (NFR-SEC-03, separation of duties)
    Rule("POST", "/versions/{id}/deploy", "deployer", ADMIN),
    Rule("GET", "/deployments", "deployer", PATHWAY_READERS),
    Rule("DELETE", "/deployments/{id}", "deployer", ADMIN),
    # patient: register and search (PAT-01)
    Rule("GET", "/patients", "patient", CLINICAL),
    Rule("POST", "/patients", "patient", CLINICAL),
    Rule("GET", "/patients/{id}", "patient", CLINICAL),
    Rule("GET", "/beds", "patient", CLINICAL),
    Rule("POST", "/beds", "patient", CLINICAL),
    Rule("POST", "/beds/{id}/release", "patient", CLINICAL),
    # worklist: tasks for my role (WRK-01)
    Rule("GET", "/tasks", "worklist", CLINICAL),
    Rule("POST", "/tasks/{id}/claim", "worklist", CLINICAL),
    Rule("POST", "/tasks/{id}/release", "worklist", CLINICAL),
    Rule("POST", "/tasks/{id}/complete", "worklist", CLINICAL),
    Rule("POST", "/tasks/{id}/fail", "worklist", CLINICAL),
    Rule("GET", "/overrides", "worklist", frozenset({"manager", "admin"})),
    Rule("GET", "/notifications", "worklist", CLINICAL | {"manager", "admin"}),
    # monitoring: case history (MON-01) and the dashboard (MON-02), plan Section 10 matrix
    Rule("GET", "/cases", "worklist", CASE_READERS),
    Rule("GET", "/cases/{id}", "worklist", CASE_READERS),
    Rule("GET", "/dashboard", "worklist", MANAGERS),
    # WRK-03: admins keep the alert contacts; managers and admins see what was sent
    Rule("GET", "/alert-contacts", "worklist", ADMIN),
    Rule("POST", "/alert-contacts", "worklist", ADMIN),
    Rule("PATCH", "/alert-contacts/{id}", "worklist", ADMIN),
    Rule("GET", "/deliveries", "worklist", MANAGERS),
)

_COMPILED = [(r, r.regex) for r in RULES]


def match(method: str, path: str) -> Rule | None:
    for rule, rx in _COMPILED:
        if rule.method == method and rx.match(path):
            return rule
    return None

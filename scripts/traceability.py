"""Traceability from story and NFR IDs to tests, diagrams and decisions (plan Section 18:
"IDs traceable from story to test to diagram"). Writes docs/closure/traceability.md.

    .venv/bin/python scripts/traceability.py

Tests are found by name (``test_ver01_…``, ``test_nfr_perf_02_…``, also several IDs in one
name such as ``test_eng02_eng03_…``); diagrams and decisions by the ID in their text.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# (id, priority, points, sprint, title) — the product backlog of plan Section 12.
BACKLOG = [
    ("AUTH-01", "Must", 3, 1, "Admin creates users with roles"),
    ("AUTH-02", "Must", 3, 1, "Log in with an expiring token"),
    ("AUTH-03", "Must", 5, 1, "Refuse actions the role does not allow"),
    ("DES-01", "Must", 8, 1, "Draw a pathway"),
    ("DES-02", "Must", 3, 1, "Variables, inputs and outputs"),
    ("DES-03", "Must", 5, 1, "Branch conditions with live syntax errors"),
    ("DES-05", "Must", 3, 1, "Publish creates an immutable version"),
    ("VER-01", "Must", 8, 2, "Deadlock blocks Publish, path highlighted"),
    ("VER-02", "Must", 5, 2, "Duplicate work, unfinished cases, livelocks"),
    ("VER-03", "Must", 2, 2, "Unreachable steps"),
    ("VER-04", "Must", 5, 2, "Data that may be unset"),
    ("VER-05", "Should", 3, 2, "Condition type errors"),
    ("VER-06", "Should", 2, 2, "Too large to verify"),
    ("DES-04", "Must", 5, 2, "Deadlines, escalation, retries, fallback, undo"),
    ("PAT-01", "Must", 3, 2, "Register and search patients"),
    ("ENG-01", "Must", 5, 3, "Registration starts a case"),
    ("ENG-02", "Must", 8, 3, "Tasks requested from the right service"),
    ("ENG-03", "Must", 5, 3, "Decisions on live data"),
    ("ENG-04", "Must", 5, 3, "Join fires exactly once"),
    ("ENG-05", "Must", 5, 3, "Duplicates never change a case twice"),
    ("WRK-01", "Must", 5, 3, "Tasks for my role"),
    ("ENG-06", "Must", 5, 4, "Escalation along the chain"),
    ("ENG-07", "Must", 5, 4, "Retry with backoff, then fallback"),
    ("ENG-08", "Must", 8, 4, "Undo in reverse order, Compensated"),
    ("ENG-09", "Must", 5, 4, "Resume after a crash"),
    ("DEP-01", "Must", 8, 4, "Deploy starts its own engine"),
    ("DES-06", "Must", 3, 5, "Durations and branch probabilities"),
    ("SIM-01", "Must", 8, 5, "Simulate a scenario"),
    ("SIM-02", "Must", 5, 5, "95% confidence intervals"),
    ("SIM-03", "Must", 8, 5, "Cheapest staffing that meets targets"),
    ("SIM-04", "Must", 3, 5, "Erlang C and Little's law validation"),
    ("DEP-02", "Should", 3, 5, "Undeploy drains, then stops"),
    ("ML-01", "Must", 8, 6, "Train and evaluate the urgency model"),
    ("ML-02", "Must", 5, 6, "PredictUrgency service"),
    ("WRK-02", "Must", 3, 6, "Override only with a reason"),
    ("PAT-02", "Must", 3, 6, "Beds with an undo action"),
    ("CLN-01", "Must", 5, 6, "Triage end to end"),
    ("CLN-02", "Must", 3, 6, "Assessment end to end"),
    ("CLN-03", "Must", 3, 6, "Visit end to end"),
    ("CLN-04", "Should", 3, 7, "New task type without engine change"),
    ("WRK-03", "Should", 3, 7, "Email or SMS alert on escalation"),
    ("MON-01", "Must", 3, 7, "Any case's full history"),
    ("MON-02", "Should", 5, 7, "Dashboards"),
    ("MON-03", "Could", 3, 7, "Service health and metrics"),
    ("SIM-05", "Could", 3, 7, "Compare two scenarios"),
    ("MIG-01", "Won't", 13, 0, "Migrate running cases (stretch)"),
]
NFRS = [
    "NFR-SEC-01", "NFR-SEC-02", "NFR-SEC-03", "NFR-SEC-04", "NFR-SEC-05", "NFR-SEC-06",
    "NFR-REL-01", "NFR-REL-02", "NFR-REL-03", "NFR-ROB-01", "NFR-PERF-01", "NFR-PERF-02",
    "NFR-PERF-03", "NFR-PERF-04", "NFR-USE-01", "NFR-USE-02", "NFR-MNT-01", "NFR-MNT-02",
    "NFR-MNT-03", "NFR-POR-01", "NFR-ORG-01", "NFR-ORG-02", "NFR-EXT-01",
]  # fmt: skip
# NFRs proven by tests or checks that do not carry the NFR id in their name.
ALSO = {
    "NFR-SEC-04": "Compose file: only the deployer mounts docker.sock (runtime test needs Docker)",
    "NFR-SEC-06": "CI security job: bandit + pip-audit",
    "NFR-REL-01": "test_eng05_…, invariant I1 (every message delivered twice)",
    "NFR-REL-02": "test_eng09_…, test_i3_replaying_1000_random_cases_…",
    "NFR-REL-03": "test_i5_crash_after_commit_before_publish_…, test_i5_crash_after_receive_…",
    "NFR-USE-01": "web model.test.ts: counterexample replay; test_every_counterexample_replays_…",
    "NFR-MNT-01": "pytest --cov (fail_under = 80)",
    "NFR-MNT-02": "CI: radon, ruff, mypy --strict",
    "NFR-POR-01": "README one-command start (not run here: Docker unavailable)",
    "NFR-ORG-01": "Scrum artefacts in docs/; burndown reconstructed from the tags (no board)",
    "NFR-ORG-02": "repository: Python 3.12 / FastAPI services, React + React Flow web",
    "NFR-EXT-01": "synthetic data only (docs/ml/model-card.md)",
}
TEST_DEF = re.compile(r"^def (test_[a-z0-9_]+)", re.M)


def test_token(ident: str) -> re.Pattern[str]:
    """``ENG-01`` → matches ``eng01`` as a word part; ``NFR-PERF-02`` → ``nfr_perf_02`` or ``perf02``."""
    parts = ident.lower().split("-")
    if parts[0] == "nfr":
        kind, num = parts[1], parts[2]
        return re.compile(rf"(?:^|_)(?:nfr_{kind}_?{num}|{kind}_?{num})(?:_|$)")
    return re.compile(rf"(?:^|_){parts[0]}_?{parts[1]}(?:_|$)")


def all_tests() -> list[tuple[str, str]]:
    found = []
    for path in sorted(ROOT.glob("**/test_*.py")):
        if ".venv" in path.parts or "node_modules" in path.parts:
            continue
        rel = str(path.relative_to(ROOT))
        found += [(rel, name) for name in TEST_DEF.findall(path.read_text())]
    return found


def mentions(folder: str, pattern: str, ident: str) -> list[str]:
    """Diagram IDs (U13) or decision numbers (0006) whose text names ``ident``."""
    return sorted(
        re.split("[_-]", p.stem)[0] for p in (ROOT / folder).glob(pattern) if ident in p.read_text()
    )


def row(ident: str, tests: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    rx = test_token(ident)
    hits = [(f, t) for f, t in tests if rx.search(t.removeprefix("test"))]
    return hits, mentions("docs/uml", "*.puml", ident), mentions("docs/decisions", "*.md", ident)


def joined(items: list[str]) -> str:
    return ", ".join(items) or "—"


def story_rows(tests: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """Table rows for the backlog, and the stories with no test carrying their ID."""
    rows, untested = [], []
    for ident, prio, pts, sprint, title in BACKLOG:
        hits, uml, dec = row(ident, tests)
        files = sorted({f.split("/tests/")[0].split("/")[-1] if "/tests/" in f else f for f, _ in hits})
        if not hits and prio != "Won't":
            untested.append(ident)
        rows.append(
            f"| {ident} | {prio} | {pts} | {sprint or '—'} | {title} | {len(hits)} ({joined(files)}) "
            f"| {joined(uml)} | {joined(dec)} |"
        )
    return rows, untested


def nfr_rows(tests: list[tuple[str, str]]) -> list[str]:
    rows = []
    for ident in NFRS:
        hits, uml, dec = row(ident, tests)
        rows.append(f"| {ident} | {len(hits)} | {ALSO.get(ident) or '—'} | {joined(uml)} | {joined(dec)} |")
    return rows


def main() -> None:
    tests = all_tests()
    stories, untested = story_rows(tests)
    lines = [
        "# Traceability: story / NFR → tests → diagrams → decisions",
        "",
        "Generated by `scripts/traceability.py`; do not edit by hand. A test counts when its name",
        "carries the ID (e.g. `test_eng05_…`). Stories proven by tests named otherwise (for example",
        "the end-to-end system tests) show the files in the last column.",
        "",
        "| ID | Priority | Pts | Sprint | Story | Tests | Diagrams | Decisions |",
        "|----|----------|----:|-------:|-------|------:|----------|-----------|",
        *stories,
        "",
        "## Non-functional requirements",
        "",
        "| NFR | Tests by name | Also proven by | Diagrams | Decisions |",
        "|-----|------:|----------------|----------|-----------|",
        *nfr_rows(tests),
        "",
        f"Tests in the repository: {len(tests)} test functions (parametrised cases counted once).",
        f"Stories without a test carrying their ID: {', '.join(untested) or 'none'}.",
        "",
    ]
    out = ROOT / "docs" / "closure" / "traceability.md"
    out.write_text("\n".join(lines))
    print(f"wrote {out.relative_to(ROOT)}; untested by name: {', '.join(untested) or 'none'}")


if __name__ == "__main__":
    main()

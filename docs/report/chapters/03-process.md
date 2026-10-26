# Development process

## Choice of process

The course slides (*4 – Software processes*) compare plan-driven (waterfall), incremental and
reuse-oriented processes. A waterfall process would fix the requirements before anything runs.
That suits stable domains, but here three algorithms of uncertain difficulty depend on each
other: the engine reuses the verifier's token rules, and the simulator reuses both. Building
them in risk order, with a working increment after each, makes problems visible early. The
project therefore follows **Scrum** (*5 – Agile development*) in its three phases:

1. **Outline planning and architectural design** — Sprint 0 and this Part I;
2. **Sprint cycles** — Sprints 1 to 7, each delivering a tagged, working increment;
3. **Project closure** — the acceptance check, the report and the presentation (Part III).

Reuse-oriented elements are used where they fit: frameworks (FastAPI, React, React Flow),
commercial off-the-shelf components (PostgreSQL, RabbitMQ) and libraries (scikit-learn, SciPy,
SHAP). Extreme Programming practices from the same deck are used inside each sprint:
test-first development for `pathway-core`, refactoring (Sprint 1 moved every route into
module-level routers to keep complexity under 10), and continuous integration on every push.

## Roles

With one person, the three Scrum roles are three hats:

| Role | Aim (from the slides) | How it was played |
|------|-----------------------|-------------------|
| Product Owner | Build the right thing; own the backlog ordered by value and risk | The professor's requirements as the customer's voice; backlog in plan Section 12 |
| Scrum Master | Build it fast; remove blockers | Blockers recorded in the daily notes (`docs/daily/`), e.g. Docker unavailable |
| Team | Build things right | The author with an AI coding assistant under written rules (chapter 14) |

## Ceremonies and artefacts

- **Sprint planning** picks the stories for a single sprint goal (each sprint chapter
  starts with it).
- **Daily scrum** is a three-line written note: done, next, blocked (`docs/daily/`).
- **Sprint review** is a demonstration in the running system; each sprint chapter reports what
  was shown in the browser.
- **Retrospective** records what to keep, stop and try; each sprint chapter ends with it.
- **Product backlog**: 46 stories with IDs, priorities (MoSCoW) and points (appendix A).
- **Increment**: working software tagged `sprint-0` … `sprint-7` in the repository.
- **Definition of Done** for every story: its acceptance criteria pass as automated tests; the
  code passed the inspection checklist; lint, types, tests, coverage of at least 80% and the
  security scan are green; its UML is updated; its ID appears in test names and commit messages;
  the notes for the sprint's report chapter are written.

### Velocity, burndown and the calendar

The plan budgeted sixteen calendar weeks: Sprint 0 of one week, seven two-week sprints and a
closure. The repository history shows something different and the report states it plainly: the
eight increments were committed on 25 and 26 October 2026 (Table 3.1), because the AI-assisted
implementation produced each sprint's stories, tests and documentation in hours rather than
weeks. The Scrum structure — one goal, one set of stories, one tagged increment, one review and
retrospective per sprint — was kept. The calendar was not.

| Tag | Committed | Stories |
|-----|-----------|---------|
| `sprint-0` | 2026-10-25 20:12 | Skeleton, pathway-core, Verifier core |
| `sprint-1` | 2026-10-25 20:40 | AUTH-01..03, DES-01..03, DES-05 |
| `sprint-2` | 2026-10-25 20:57 | VER-01..06, DES-04, PAT-01, NFR-USE-01 |
| `sprint-3` | 2026-10-25 21:32 | ENG-01..05, WRK-01 |
| `sprint-4` | 2026-10-25 22:24 | ENG-06..09, DEP-01 |
| `sprint-5` | 2026-10-25 22:49 | DES-06, SIM-01..04, DEP-02 |
| `sprint-6` | 2026-10-25 23:23 | ML-01/02, WRK-02, PAT-02, CLN-01..03 |
| `sprint-7` | 2026-10-26 14:32 | CLN-04, WRK-03, MON-01..03, SIM-05, NFR hardening |

: Table 3.1 — Sprint increments as recorded in git.

Two consequences follow. First, **no burndown chart** exists: the plan required burndown "from
real board data, never redrawn by hand" (NFR-ORG-01), and no project board was kept during the
two days, so none is drawn. Second, the velocity chart (Figure 3.1) shows story points per
increment, not per two weeks. Every increment delivered exactly the points planned for it,
207 in total. With an assistant producing the code, velocity measures the plan's slicing
rather than the team's capacity.

{{chart velocity "Figure 3.1 — Story points delivered per increment (from the backlog and the tags)."}}

## Tools

| Purpose | Tool |
|---------|------|
| Language and services | Python 3.12 (Docker images; 3.13 locally), FastAPI, SQLAlchemy 2, Pydantic |
| Web app | React 19, @xyflow/react (React Flow) 12, TypeScript, Vite, Vitest |
| Messaging and data | RabbitMQ topic exchange (in Compose), an in-memory bus with fault injection (tests and the development stack), PostgreSQL 16 (one schema per service), SQLite in tests |
| Quality gate | ruff (style, complexity), mypy --strict, pytest with coverage, Hypothesis, radon, bandit, pip-audit, gitleaks |
| Delivery | Docker Compose, GitHub Actions workflow (`.github/workflows/ci.yml`) |
| Modelling | PlantUML, kept in `docs/uml/` beside the code |
| AI assistance | Claude Code, under `CLAUDE.md` rules (chapter 14) |

## AI tooling architecture

The professor asked for an explicit AI tooling architecture (requirement P20). Table 3.3 shows
which tool was used in which phase and the human checkpoint after each. Chapter 14 evaluates it.

| Phase | Tool | Used for | Checkpoint |
|-------|------|----------|------------|
| Requirements and design | Claude (chat) | Drafting the proposal's stories and algorithms; challenging the design | The plan, approved before code; UML in the repository |
| Implementation | Claude Code | Code for one sprint's stories at a time, from the plan's algorithms and acceptance criteria | Tests pass; the full quality gate; review against the inspection checklist |
| Testing | Claude Code | Test cases, property-based generators, fault injection, load tests | Every generated test read; tests that proved nothing were rewritten (Sprint 5) |
| Documentation | Claude Code | Prompt logs, decisions, this report's drafts | Claims checked against code and measurements (e.g. an overclaim corrected in Sprint 7) |

: Table 3.3 — AI tooling architecture.

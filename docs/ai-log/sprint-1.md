# Prompt log — Sprint 1: pathway model, editor, login

Sprint goal: draw, save and version a pathway; role checks work.
Stories: AUTH-01, AUTH-02, AUTH-03, DES-01, DES-02, DES-03, DES-05 (30 points).
UML: U04 (pathway model), U05 (condition language), E1 (tables per service). Tool: Claude Code.

## AUTH-01/02 — auth service
- **Prompt summary:** "Start Sprint 1: the React Flow pathway editor and the auth service with JWT and roles."
- **Produced:** users and login log tables, bcrypt hashing, access (15 min) and refresh (8 h)
  JWTs, `/auth/login`, `/auth/refresh`, `/auth/me`, `/users` for admins, first admin seeded from env.
- **Design choices to check in review:** users are deactivated, never deleted (audit trail);
  an admin cannot demote or deactivate themself; the role is re-read at refresh.
- **Tests:** 11, including expired, forged and wrong-kind tokens (NFR-SEC-01).

## AUTH-03 — gateway permission matrix
- **Produced:** routing rules with allowed roles per route, token check, proxy with identity
  headers, deny by default. Decision 0002 records the trust model and its limits.
- **Tests:** every rule × every role (85 cases), plus spot checks taken from Section 10.

## DES-01/02/03/05 — designer service and editor
- **Produced:** pathways and versions (draft → verified → published), Verify calls Algorithm 1,
  Publish needs a SAFE report of the exact version, published versions are immutable,
  `/conditions/check` uses pathway-core's parser and type checker; React Flow editor with
  palette, inspector (tasks: kind, role/service, inputs/outputs, deadline and escalation,
  retries, fallback, undo, duration), variables panel, live condition errors with a caret,
  Verify report with the error nodes and counterexample path highlighted.
- **Where the AI was wrong and testing caught it (keep for the report, Section 14 item 4):**
  1. *Nodes invisible on the canvas* (found in the browser, not by unit tests). The editor
     loaded the model a second time after React Flow had measured the nodes; the new node
     objects had no measurements and nothing re-measured them, so React Flow kept them hidden.
     Cause: the load callback depended on `useReactFlow()`, which changed identity. Fix: stable
     callback and the canvas remounts on every load.
  2. *A branch could not be selected.* With right-angle arrows, the CT branch ran along the same
     line as the X-ray branch, so clicks always hit CT. Fix: curved arrows, which separate at
     the decision, and a wider click area. Usability problem for NFR-USE-01.
  3. *Edges without ids.* Hand-written pathway JSON (triage.json) has edges without `id`; the
     editor crashed while pathway-core generated ids. Caught by the unit test that round-trips
     triage.json. Fix: the same default id as pathway-core.
  4. *FastAPI could not resolve dependencies* declared inside `create_app` when
     `from __future__ import annotations` was on (every endpoint returned 422). Caught by the
     first auth test run. Later the routes moved to module-level routers anyway, to keep each
     function's cyclomatic complexity under 10 (NFR-MNT-02).
- **Tests:** designer 11 (with the real Verifier in-process), web 7 (model round trip, layout,
  helpers). Browser check: log in, open the deadlock example, Verify → UNSAFE with the path
  highlighted, replace the join with a merge by drawing, Verify → SAFE (8 states), Publish → read-only.

## Not done in this sprint (carried over)
- Step-by-step counterexample replay on the canvas (NFR-USE-01, Sprint 2).
- Playwright end-to-end tests of the editor (Sprint 3, when the system tests start).
- Alembic migrations (tables are created at start-up for now).

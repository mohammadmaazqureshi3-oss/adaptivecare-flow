# AdaptiveCare Flow

A low-code platform for clinical pathways. Staff draw a pathway in an editor; the
system proves it is safe (Algorithm 1, Verifier), predicts how many staff it needs
(Algorithm 3, Simulator and Staffing Advisor), deploys it as its own microservice
and runs it for every patient (Algorithm 2, Execution Engine).

Plan of record: `../sofware project_proposal.docx` (Final Project Plan, 23 Oct 2026).

## Start everything (NFR-POR-01)

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:8080> and sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`.
<http://localhost:8000/health/all> shows every service's health.

### Without Docker (the services built so far)

`dev.sh` runs every built service in one process with an in-memory bus in place of RabbitMQ.
The deployer runs there with a local runtime: pressing Deploy (as admin) starts that version's
engine in the same process instead of a Docker container.

```bash
./scripts/dev.sh                          # gateway :8000 … ml :8006, deployer :8007, engines :8010+
.venv/bin/python scripts/seed_demo.py     # demo users, pathways (Triage published and deployed), patients
npm --prefix web install && npm --prefix web run dev   # editor on http://localhost:5173
```

Demo accounts (development only) are listed in `scripts/seed_demo.py`.

## Develop and test

```bash
python3 -m venv .venv
.venv/bin/pip install -e packages/pathway-core -r requirements-dev.txt
.venv/bin/python -m pytest --cov
.venv/bin/ruff check packages services
.venv/bin/mypy packages/pathway-core/src services/verifier/verifier services/auth/auth services/gateway/gateway services/designer/designer services/patient/patient \
  services/engine/engine services/worklist/worklist services/ml/ml services/deployer/deployer \
  packages/care-events/src
npm --prefix web test && npm --prefix web run typecheck
```

If `import pathway_core` fails outside the repo root on macOS with Python 3.13, macOS has
marked the venv's `.pth` files hidden and Python skips them. Fix:
`chflags nohidden .venv/lib/python3.*/site-packages/*.pth`

Run the verifier on its own:

```bash
cd services/verifier && ../../.venv/bin/uvicorn verifier.main:app --reload
curl -s -X POST localhost:8000/verify -H 'content-type: application/json' -d @../../pathways/imaging_deadlock.json
```

## Repository layout

| Path | What it is |
|------|------------|
| `packages/pathway-core/` | Pathway model, the eight token rules, condition language, task settings (DES-04) |
| `services/verifier/` | **Algorithm 1** — state-space search, soundness checks, data-flow fixed point, counterexamples |
| `services/auth/` | Users, roles, bcrypt, JWT access/refresh tokens (AUTH-01/02) |
| `services/gateway/` | Single entry point: token check, permission matrix, proxy (AUTH-03) |
| `services/designer/` | Pathways, versions, Verify, Publish, live condition checks (DES-01..05) |
| `services/patient/` | Register and search patients (PAT-01); publishes `PatientRegistered` |
| `packages/care-events/` | Event envelope, bus (in-memory and RabbitMQ), outbox and inbox |
| `services/engine/` | **Algorithm 2** — token interpreter, event store, replay, snapshots, timers, retries, escalation, compensation |
| `services/worklist/` | Tasks for people: claim and complete with required outputs (WRK-01) |
| `services/ml/` | Placeholder until Sprint 6: answers `PredictUrgency` with a permanent failure |
| `services/deployer/` | Deploy: PIM → PSM, start the engine, health check, `PathwayDeployed` (DEP-01) |
| `services/simulator/` | Service skeleton (Sprint 0) |
| `tests/system/` | In-process system test: patient → engine → ml → worklist |
| `web/` | React + React Flow pathway editor and admin pages |
| `scripts/` | `dev.sh` (run without Docker), `seed_demo.py` (demo users and pathways) |
| `pathways/` | `triage.json` (SAFE), `imaging_deadlock.json` (the worked example, UNSAFE), `imaging_fixed.json` |
| `contracts/events.md` | Event envelope and catalog, REST contract |
| `docs/uml/` | PlantUML diagrams (U01–U21, U31, U32, E1) |
| `docs/ai-log/` | Prompt log per sprint (requirement P21) |
| `docs/daily/` | Daily scrum notes |
| `CLAUDE.md` | Rules file for AI tools |

## Status

| Sprint | Goal | State |
|--------|------|-------|
| 0 | Outline planning and architecture | Skeleton, CI, rules file, UML drafts done |
| 1 | Pathway model, editor, login | Done: auth, gateway permission matrix, designer, React Flow editor |
| 2 | Algorithm 1: Verifier | Done: Verifier, counterexample replay (NFR-USE-01), task settings (DES-04), patients (PAT-01), UML U07–U12 |
| 3 | Algorithm 2: Engine core | Done: ENG-01..05, WRK-01, fault-injection and replay tests; RabbitMQ run pending (Docker) |
| 4 | Algorithm 2 reliability and Deploy | Done: ENG-06..09, DEP-01; Docker runtime and RabbitMQ not yet run (Docker) |
| 5–7 | Simulator, ML, clinical pathways, hardening | Not started |

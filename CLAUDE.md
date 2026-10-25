# AdaptiveCare Flow — rules for AI coding tools

This file is under version control and is part of the AI tooling architecture
(plan Section 14, requirement P21). Every AI tool used on this repository must follow it.

## Stack (NFR-ORG-02)
- Python 3.12, FastAPI for every service; React + React Flow for the web app.
- RabbitMQ (one topic exchange `care.events`), PostgreSQL 16 (one schema per service).
- Docker Compose for the platform; one engine container per deployed pathway version.

## Folder layout
- `packages/pathway-core/` — pathway model, token rules, condition language. Shared by verifier, simulator, engine.
- `services/<name>/<name>/` — one FastAPI service per folder; `services/<name>/tests/` for its tests.
- `contracts/` — event schemas and API contracts.
- `pathways/` — example and clinical pathway models (JSON).
- `docs/uml/` — PlantUML diagrams (IDs U01–U32, E1). `docs/ai-log/` — prompt log per sprint. `docs/daily/` — daily scrum notes.

## Rules
1. Never change `contracts/` (event schemas and APIs) without a recorded design decision in `docs/decisions/`.
2. Write or update tests first. Name tests with the story or NFR ID they prove (e.g. `test_ver01_...`).
3. Take token rules only from `pathway-core`. No service re-implements how a pathway moves.
4. Keep secrets, tokens and patient identifiers out of code and logs. Configuration comes from `.env`.
5. Every public function has a docstring. Cyclomatic complexity at most 10 per function (ruff C90).
6. `ruff check`, `ruff format`, `mypy --strict` and `pytest --cov` (≥ 80% on core packages) must pass.
7. Every event handler is duplicate-safe (filter by `event_id`) and runs inside the case lock.
8. One story at a time, from its UML and acceptance tests. Story ID in the commit message.
9. Code that the author cannot explain is not merged: each pull request contains the author's own explanation.

## Commands
```bash
python3 -m venv .venv && .venv/bin/pip install -e packages/pathway-core -e packages/care-events -r requirements-dev.txt
.venv/bin/python -m pytest --cov
.venv/bin/ruff check packages services && .venv/bin/mypy packages/pathway-core/src services/verifier/verifier services/auth/auth services/gateway/gateway services/designer/designer services/patient/patient services/engine/engine services/worklist/worklist services/ml/ml services/deployer/deployer services/simulator/simulator packages/care-events/src
cp .env.example .env && docker compose up --build
```

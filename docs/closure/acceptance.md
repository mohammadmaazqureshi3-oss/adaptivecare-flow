# Acceptance checklist (Closure)

Plan Section 13 (User: acceptance): "Section 2's requirement table checked row by row".
Checked against the delivered system at tag `sprint-7` plus the Closure changes, 2026-10-26.
Status: ✅ met · ⚠️ met with a stated limit · ❌ not met · 👤 needs you (cannot be done or
proven from the repository).

## Section 2 — the professor's requirements

| ID | Requirement | Evidence in the delivered system | Status |
|----|-------------|----------------------------------|--------|
| P1 | AI or rule features are not complex | Category 3 = Verifier, Engine, Simulator; the model is Category 2 (`services/ml`), rules are pathway settings | ✅ |
| P2 | Really programmable and customizable | Editor (`web/src/editor`), condition language with parser and type checker (`pathway_core.conditions`), per-step settings (`pathway_core.settings`), plug-in task services (`services/scores`, CLN-04) | ✅ |
| P3 | A clinical workflow engine | `services/engine` (Algorithm 2); 50+ engine tests including fault injection | ✅ |
| P4 | An IDE for triage, assessment, visit | React Flow editor with live condition checks, Verify with replay, Simulate, Compare, versions, Deploy | ✅ |
| P5 | Deploy and run as microservices | Deployer generates a PSM and starts one engine per version (`services/deployer`, `DockerRuntime`) | ⚠️ Docker runtime not run here (Docker unavailable); the local runtime is tested and used in the dev stack |
| P6 | Event-driven | One topic exchange, outbox/inbox, catalog in `contracts/events.md` | ⚠️ RabbitMQ adapter not run here (Docker); the in-memory bus with fault injection is tested |
| P7 | Implement workflows with the system | `pathways/clinical/` Triage v4, Assessment, Visit: verified SAFE, simulated, deployed and run end to end (`tests/system/test_clinical_pathways.py`) | ✅ |
| P8 | Every feature in a category with motivation | Four-category table (plan Section 4, report chapter 4) | ✅ |
| P9 | Balanced categories; NFRs explicit | NFR table with IDs and measurements (`docs/measurements/nfr-results.md`) | ✅ |
| P10 | Category 3 is algorithmic or orchestration, not UI | Verifier and Simulator algorithmic; Engine orchestration; editor never claimed | ✅ |
| P11 | Model call is Category 2; Category 3 only inside a workflow | Triage routes on the model's output through the Engine (decision node) | ✅ |
| P12 | Self-assess; rebalance | Report chapter 4 balance note | ✅ |
| P13 | Honest categorization | Retries, timers, outbox, deployment generation filed as Category 4 | ✅ |
| P14 | Approval before implementation | The repository cannot show the professor's reply | 👤 keep his written approval; Sprint 0 is dated 25 Oct 2026 |
| P15 | Highly detailed report | `docs/report/` (Markdown chapters) → `docs/report/AdaptiveCare-Flow-Report.docx` | ✅ (see the page count in the build output) |
| P16 | One report section per sprint | Report chapters 6–13 = Sprints 0–7 | ✅ |
| P17 | Standard artifacts and UML | Backlog with IDs (`docs/closure/traceability.md`), 32 UML + E1 (`docs/uml`), velocity per increment | ⚠️ no burndown from board data (see below) |
| P18 | Complex logic in activity, sequence, state diagrams | Verifier U07–U11, Engine U13–U20, Simulator U22–U25 | ✅ |
| P19 | Category 3 complexity evident in the design | Algorithms specified in the plan before code; UML in the repository, checked in Closure (`docs/closure/uml-check.md`) | ✅ |
| P20 | AI tooling architecture | Report chapter 14, `CLAUDE.md` | ✅ |
| P21 | Prompts, constraints, refinement documented | `CLAUDE.md`, `docs/ai-log/sprint-0..7.md` | ✅ |
| P22 | V&V of AI output | Tests first, 664 tests (648 Python, 13 web unit, 3 browser), ruff/mypy/radon/bandit/pip-audit in CI; each AI log lists where the AI was wrong | ✅ |
| P23 | You own and can explain the logic | Explain-back rule (CLAUDE.md rule 9); Q&A preparation in `docs/closure/rehearsal.md` | 👤 your explanation in the presentation |
| E1 | Algorithmic, not merely computational | State-space search, orchestration with invariants, discrete-event simulation | ✅ |
| E2 | Rule and policy customizability | Conditions, escalation chains, retries, answer timeouts, fallbacks, undo, override checks, announced events | ✅ |
| E3 | Requirements uniquely identified | IDs in tests, diagrams, decisions and commits (`docs/closure/traceability.md`) | ✅ |
| E4 | Report and code match; tagged per sprint | Tags `sprint-0`…`sprint-7`; diagrams checked against the code in Closure | ✅ |
| E5 | No navigation service | None | ✅ |

## Section 18 — before submission

| Item | Status |
|------|--------|
| Every row of Section 2 checked against the delivered system | ✅ this file |
| Each algorithm has activity, sequence and state machine diagrams that match the code | ✅ `docs/closure/uml-check.md` (checked by reading; rendering needs PlantUML: `scripts/render_uml.sh`) |
| Fault-injection, property-based and simulator validation tests pass in CI | ✅ locally (I1–I5, Hypothesis, Erlang C 92/100); CI not run: there is no remote repository |
| Every NFR measured and reported, including any missed | ✅ `docs/measurements/nfr-results.md`; NFR-ROB-01 was found unmet in Closure and fixed (decision 0008); NFR-USE-02 still open |
| Triage, Assessment, Visit verified, simulated, deployed and run end to end | ✅ dev stack and system tests |
| Report about 120 pages, by Scrum phases and sprints, traceable IDs | ✅ draft built; review it and add your own retrospective notes |
| Repository tagged per sprint; README starts everything with one command | ⚠️ tags ✅; `docker compose up --build` never run on this machine (NFR-POR-01) |
| Demo rehearsed three times and a backup video recorded | 👤 script and checklist in `docs/closure/rehearsal.md` |
| You can explain every algorithm without notes | 👤 |

## Product backlog

All 45 Must/Should/Could stories are done (each has tests; see `traceability.md`). MIG-01
(Won't, stretch) was not attempted. Points delivered: 30 + 33 + 33 + 31 + 30 + 30 + 20 = 207
(plus Sprint 0's baseline), exactly the planned points.

## Things the report must state honestly

1. **Calendar.** The plan budgets 16 weeks of two-week sprints. The repository history shows
   the increments `sprint-0`…`sprint-7` committed on 25–26 October 2026: they were built as
   rapid AI-assisted increments, not over 16 calendar weeks. The report says so.
2. **No board, no burndown.** NFR-ORG-01 asks for burndown charts from real board data.
   There was no GitHub Projects board, so the report shows points delivered per increment
   (velocity) from the tags and says that a burndown could not be produced. ❌ NFR-ORG-01
   as written.
3. **Docker.** Compose, RabbitMQ and the Docker runtime have never been run (P5, P6,
   NFR-POR-01, NFR-SEC-04 runtime test). ⚠️
4. **Alpha test.** Not run yet (NFR-USE-02); the kit is ready. 👤
5. **Data.** The urgency model is trained on synthetic data (risk R6); its figures prove the
   pipeline, not clinical accuracy.

## Plan items not delivered (final audit, 2026-10-26)

A last pass over the whole plan, beyond the backlog, found these smaller items missing or done
differently. None is a backlog story; each is stated here and in report chapter 16.

| Plan item | Where in the plan | State |
|-----------|-------------------|-------|
| Structured logs with case IDs | C4-06 | **Built after the audit** (decision 0009): JSON lines with `case_id`; seen working in the dev stack |
| HTTPS | C4-03 | **Built after the audit** (decision 0009): nginx on 443 with TLS 1.2/1.3 and a generated certificate; configuration tested, not run (no Docker) |
| Playwright tests of the web app | Section 14 (system, scenario) | **Built after the audit**: 3 browser tests in `web/e2e/`, passing against the dev stack |
| Testcontainers (real PostgreSQL in component tests) | Section 14 | Not done: component tests use SQLite (needs Docker) |
| Grafana | Section 9 (Should) | **Built after the audit**: provisioned dashboard in the `monitoring` profile; configuration tested, not run (no Docker) |
| Training in a notebook | Section 11 | Done as a script (`services/ml/training/train.py`) instead |
| Simulator urgency mix from the dataset | Section 11 | **Built after the audit**: the training data's mix is the simulator's default |
| Review videos and screenshots per sprint; sprint task boards with hours | Section 13 | Not done |
| REST names `/tasks/{id}/override`, `/cases/{id}/history`, `/dashboards` | Section 9 | Same function under other names: a reason on `/complete`, `/cases/{id}`, `/dashboard` |
| A "triage records" table in the patient schema | Section 11 | Triage results live in the case history, not in a table |

The audit also found and fixed one demo problem: the seed script did not restore the
"Imaging (has a deadlock)" draft after it had been fixed in an earlier review, so demo step 1
would have shown a SAFE pathway. `scripts/seed_demo.py` now resets it. The live smoke test
(registration → Triage → Assessment → Visit → occupied bed, overrides, monitoring, security,
Verify, Simulate) then passed 16 of 16 checks.

## What only you can do
- Confirm the professor's approval (P14).
- Run the alpha test with 3–5 classmates and score it (`docs/alpha-test/`).
- Start Docker once and run `docker compose up --build` (then `--profile monitoring`), and
  the demo against it.
- Render the diagrams (`PLANTUML_JAR=… scripts/render_uml.sh`), then rebuild the report so
  the figures appear.
- Rehearse the talk three times and record the backup video.
- Fill in "Kept / changed" in `docs/ai-log/sprint-0.md` (left for your own review).

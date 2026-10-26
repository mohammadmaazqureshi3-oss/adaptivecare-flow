# Requirements

This chapter follows the course slides *6 – Requirements engineering*: vision and stakeholders,
use cases and user stories, non-functional requirements typed as product, organisational or
external, the four-category feature table the professor asked for, and the validation checks.

## Vision and stakeholders

*For emergency departments whose pathways change faster than their software, AdaptiveCare Flow
is a platform in which staff draw a pathway, prove it safe, size its staffing and run it —
without writing code. Unlike a general workflow engine, it verifies and simulates a pathway with
exactly the semantics it executes.*

| Stakeholder | Interest | Role in the system |
|-------------|----------|--------------------|
| Pathway designer (clinical lead) | Change the pathway safely and quickly | `designer` |
| Nurse, charge nurse | Clear tasks, fewer missed deadlines; the last word on urgency | `nurse`, `charge_nurse` |
| Doctor | Tasks, results, the patient's journey | `doctor` |
| Department manager | Staffing that meets the targets; dashboards and alerts | `manager` |
| IT administrator | Users, deployment, health of the services | `admin` |
| Patient | Correct and timely care; privacy | data subject (encrypted identifiers) |
| Professor | Requirements P1–P23 and E1–E5 (chapter 16) | customer |

## Use cases

Figures 4.1 to 4.3 show the use cases for the whole system, for design time and for run time.
They are drawn in the final state: the charge nurse inherits the nurse's use cases and receives
escalations, and the scores service is an external actor like the ML service.

{{uml U01}}

{{uml U02}}

{{uml U03}}

## Product backlog

The backlog has 46 user stories in eleven groups: authentication (AUTH), design (DES),
verification (VER), patients and beds (PAT), engine (ENG), worklist (WRK), deployment (DEP),
simulation (SIM), machine learning (ML), clinical pathways (CLN) and monitoring (MON). Each has a
MoSCoW priority and story points. Appendix A lists them all, with the sprint that delivered each
and the tests that prove it. The core stories have written acceptance criteria in
Given–When–Then form. Examples:

- **VER-01** — *Given* a decision that feeds a parallel join, *when* I press Verify, *then* the
  result is UNSAFE, the deadlock is listed and its path is highlighted. *Given* the corrected
  pathway, *then* the result is SAFE and Publish is enabled.
- **ENG-05** — *Given* every message delivered twice, *when* 100 cases run, *then* every case
  history equals the history of a run without duplicates.
- **ENG-08** — *Given* a transfer that fails with no fallback after bed and lab steps finished,
  *then* the lab order is cancelled before the bed is released and the case ends Compensated.
- **SIM-04** — *Given* an M/M/c scenario, *when* the validation test runs 100 experiments, *then*
  the Erlang C value falls inside the interval at least 90 times.

The clinical pathways serve as **scenarios** in the sense of the requirements slides: Triage
(CLN-01), Assessment (CLN-02) and Visit (CLN-03) each exercise a different part of the language —
the model's output in a decision, parallel branches with a join, and an undoable reservation.

## Non-functional requirements

Every NFR has an identifier, a measurable target and a test. Table 4.2 types them with the three
kinds from the slides. Chapter 16 reports the measured result for each.

| ID | Requirement | Type | Verified by |
|----|-------------|------|-------------|
| NFR-SEC-01 | Every API call needs a valid token; access tokens expire after 15 minutes, refresh tokens after 8 hours | Product | Tests with missing, expired and forged tokens |
| NFR-SEC-02 | Every endpoint enforces the permission matrix | Product | One allowed and one denied test per role and endpoint |
| NFR-SEC-03 | Separation of duties: designers publish, only admins deploy | Product | Role tests on the deploy endpoint |
| NFR-SEC-04 | Least privilege: only the deployer can reach the Docker socket | Product | Compose inspection; access test from another container |
| NFR-SEC-05 | Patient name and birth date encrypted at rest; keys outside the repository | Product | Database inspection test; secret scan |
| NFR-SEC-06 | No high-severity findings from bandit or pip-audit | Product | CI security job |
| NFR-REL-01 | No event changes a case twice | Product | Duplicate-delivery fault injection (I1) |
| NFR-REL-02 | After the engine is killed mid-case, every case resumes with identical state | Product | Kill-and-replay test (I3) |
| NFR-REL-03 | No requested task is lost between saving and sending | Product | Crash between commit and publish (I5) |
| NFR-ROB-01 | With the ML service down, triage continues through the fallback within 2 retries | Product | Scenario test with the ML service stopped |
| NFR-PERF-01 | Verifier ≤ 2 s for 30 nodes and 4 parallel branches | Product | Timed test |
| NFR-PERF-02 | Engine handles an event in ≤ 200 ms at the 95th percentile at 50 events/s | Product | Load test |
| NFR-PERF-03 | 30 replications of 7 days for a 20-node pathway in ≤ 60 s | Product | Timed test |
| NFR-PERF-04 | ML prediction ≤ 100 ms at the 95th percentile | Product | Load test on the model |
| NFR-USE-01 | Verification errors on the canvas within 2 s, counterexample replayable step by step | Product | Scenario test |
| NFR-USE-02 | Alpha test with 3–5 classmates gives a SUS score ≥ 70 | Product | SUS questionnaire |
| NFR-MNT-01 | ≥ 80% coverage on the core packages; branch coverage reported | Product | coverage.py in CI |
| NFR-MNT-02 | Cyclomatic complexity ≤ 10 per function; ruff and mypy pass | Product | radon, ruff, mypy in CI |
| NFR-MNT-03 | A new task type is added as a new service without changing engine code | Product | CLN-04 |
| NFR-POR-01 | The whole system starts with one command on macOS (Apple silicon) and Linux | Product | Fresh-machine start |
| NFR-ORG-01 | Scrum with two-week sprints; burndown from real board data | Organisational | Board history |
| NFR-ORG-02 | Python 3.12 with FastAPI; React with React Flow | Organisational | Repository |
| NFR-EXT-01 | Only synthetic or public de-identified data; licences respected | External | Data sources section |

: Table 4.2 — Non-functional requirements.

### Permission matrix

The matrix (Table 4.3) is implemented in one place, the gateway's routing rules
(`services/gateway/gateway/permissions.py`), and tested for every route and every role.

| Capability | Admin | Designer | Nurse / charge nurse | Doctor | Manager |
|------------|:-----:|:--------:|:--------------------:|:------:|:-------:|
| Manage users and roles; alert contacts | ✓ | | | | |
| Create, edit, verify, publish pathways | | ✓ | | | |
| Read pathways and versions | ✓ | ✓ | | | ✓ |
| Run, view and compare simulations | | ✓ | | | ✓ |
| Deploy or undeploy | ✓ | | | | |
| Register patients, manage beds | | | ✓ | ✓ | |
| See and complete tasks for own role; override with a reason | | | ✓ | ✓ | |
| View cases and their history | ✓ | | | ✓ | ✓ |
| Dashboards, alerts sent, override log | ✓ | | | | ✓ |
| Service health and metrics | ✓ | | | | |

: Table 4.3 — Permission matrix as implemented.

## Feature categories

The professor asked for every feature to be placed in one of four categories with its reason,
with Category 3 reserved for complex custom logic designed by the student (requirements P8–P13).
Table 4.4 is the final categorisation, updated with the Sprint 7 features.

| ID | Category | Feature | Why it belongs here |
|----|----------|---------|---------------------|
| C1-01 | 1. Data | Users and roles | Create, read, update, deactivate |
| C1-02 | 1. Data | Patients, beds | Plain record management (encryption is C4-03) |
| C1-03 | 1. Data | Pathway and version repository | Stores models; checking them is Category 3 |
| C1-04 | 1. Data | Worklist tasks, override log | Records of who must do what, and who changed what |
| C1-05 | 1. Data | Case list and case history | Read-only views over recorded events |
| C1-06 | 1. Data | Simulation scenarios, results, comparison | Saving and comparing inputs and outputs |
| C1-07 | 1. Data | Dashboards | Standard counts and means |
| C1-08 | 1. Data | NEWS2 score service | A published formula; shows the plug-in mechanism, not complexity |
| C2-01 | 2. Third party | React Flow | Ready-made canvas |
| C2-02 | 2. Third party | RabbitMQ | Ready-made broker |
| C2-03 | 2. Third party | PostgreSQL | Ready-made database |
| C2-04 | 2. Third party | scikit-learn and SHAP | Library urgency model and explanations |
| C2-05 | 2. Third party | NumPy and SciPy | Distributions and t-quantiles |
| C2-06 | 2. Third party | Docker Engine API | Starting and stopping containers |
| C2-07 | 2. Third party | SMTP / HTTP SMS gateway | Sending escalation alerts |
| C2-08 | 2. Third party | PyJWT, bcrypt, cryptography (Fernet) | Tokens, password hashing, encryption |
| C3-01 | 3. Complex | Algorithm 1: Pathway Verifier | Algorithmic processing: state-space search with formal properties |
| C3-02 | 3. Complex | Algorithm 2: Execution Engine | Business orchestration across services, with the model's output driving decisions |
| C3-03 | 3. Complex | Algorithm 3: Simulator and Staffing Advisor | Algorithmic processing: simulation, statistics and a staffing search |
| C4-01 | 4. Architecture | Event-driven microservices | Eleven services, publish-subscribe, interpreter-style engine |
| C4-02 | 4. Architecture | Deployment | Per-version engines from a generated configuration; Compose; CI |
| C4-03 | 4. Architecture | Security | JWT, roles, separation of duties, least privilege, encrypted identifiers, scans |
| C4-04 | 4. Architecture | Reliability | Outbox, duplicate-safe consumers, replay, retries, answer timeouts, persisted timers |
| C4-05 | 4. Architecture | Performance | Measured targets for each algorithm, load and stress tests |
| C4-06 | 4. Architecture | Observability | Case monitor, metrics per route, service health, Prometheus |
| C4-07 | 4. Architecture | Usability | Errors on the canvas, counterexample replay, interval charts, SUS test |
| C4-08 | 4. Architecture | Maintainability | Shared pathway-core, coverage and complexity limits, typed code |

: Table 4.4 — Features by category.

**Sub-algorithms inside Category 3.** *Verifier:* reachability exploration over markings,
co-reachability analysis, dead-step detection, data-flow fixed point, condition type checking,
counterexample reconstruction. *Engine:* token interpreter, event correlation by wait id,
duplicate filtering, join synchronisation under concurrency, condition evaluation,
event-sourced recovery, compensation ordering. *Simulator:* future-event list, thinning,
priority queues, replications with confidence intervals, greedy staffing search, validation
against queueing theory.

**Not claimed as complex, deliberately** (requirement P13): the editor screens, all CRUD, the ML
model, NEWS2, retries, timers and the outbox (reliability patterns), escalation rules (designer
settings the engine executes), deployment configuration generation (template-based), and the
monitoring.

**Balance** (requirement P12): 8 data features, 8 third-party components, 3 algorithms and 8
architecture items. Category 3 has fewer rows because each row is a large algorithm made of
several sub-algorithms: the three services hold about 2,700 of the repository's 13,000
non-test lines, about 3,700 with the shared `pathway-core` library they all use, and they carry
most of the tests.

## Validation of the requirements

The checks from the requirements slides were applied to the backlog before Sprint 1 and again
in Closure:

- **Validity** — every story traces to a professor requirement or to a clinical scenario
  (appendix A).
- **Consistency** — one conflict was found and resolved. The plan's Triage example predicted
  urgency in parallel with measuring the vital signs the model needs. Triage v2 measures first
  (decision 0006).
- **Completeness** — each pathway element has rules for the verifier, the engine and the
  simulator. One gap was found in Closure: NFR-ROB-01 assumed a failing ML service, not a
  silent one, and was fixed with answer timeouts (decision 0008).
- **Realism** — the scope was cut once in planning (`MIG-01`, migrating running cases, is
  Won't).
- **Verifiability** — every NFR has a number and a test. NFR-ORG-01's "burndown from board data"
  turned out unverifiable in practice (chapter 3).

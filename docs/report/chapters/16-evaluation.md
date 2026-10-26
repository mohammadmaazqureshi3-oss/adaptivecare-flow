# Evaluation and lessons learned

## Results against the NFR targets

Every NFR was measured, and the ones not met are reported with the reason (plan Section 10).

| NFR | Target | Measured | Status |
|-----|--------|----------|--------|
| NFR-SEC-01 | Valid token on every call; 15 min / 8 h | missing, expired, forged and wrong-kind tokens refused | met |
| NFR-SEC-02 | Permission matrix on every endpoint | every rule × every role tested | met |
| NFR-SEC-03 | Designers publish, only admins deploy | role tests on deploy | met |
| NFR-SEC-04 | Only the deployer reaches the Docker socket | Compose file: only the deployer mounts it | partly: the access test from another container needs Docker |
| NFR-SEC-05 | Identifiers encrypted; keys outside the repository | raw-database inspection finds no name or date | met |
| NFR-SEC-06 | No high findings from bandit or pip-audit | none | met |
| NFR-REL-01 | No event changes a case twice | every message twice, 100 cases | met |
| NFR-REL-02 | Identical state after a crash | 50 cases killed and restarted; 1,000 replayed | met |
| NFR-REL-03 | No task lost between saving and sending | crash after commit, before publish | met |
| NFR-ROB-01 | ML down → fallback within 2 retries | 3 unanswered attempts, then manual triage (33.5 s, live) | met after the Closure fix |
| NFR-PERF-01 | Verifier ≤ 2 s (30 nodes, 4 branches) | 0.04 s | met |
| NFR-PERF-02 | Engine p95 ≤ 200 ms at 50 events/s | p95 3 ms at about 250 events/s | met (in-process; not over RabbitMQ) |
| NFR-PERF-03 | 30 × 7 days, 20 nodes ≤ 60 s | 5.0 s | met |
| NFR-PERF-04 | ML p95 ≤ 100 ms | 11 ms | met |
| NFR-USE-01 | Errors on the canvas ≤ 2 s; step-by-step replay | Verify answers in under 1 ms on the server; replay implemented and tested | met |
| NFR-USE-02 | SUS ≥ 70 in an alpha test | not yet run | **open** |
| NFR-MNT-01 | ≥ 80% coverage on the core packages | 92.6–98.9% on the four core packages; 94.3% overall (branches 86.5%) | met |
| NFR-MNT-02 | Complexity ≤ 10; ruff and mypy | no function above 10; both pass | met |
| NFR-MNT-03 | New task type without engine change | NEWS2 service | met |
| NFR-POR-01 | One-command start on macOS and Linux | not run (no Docker on the measuring machine) | **open** |
| NFR-ORG-01 | Two-week sprints; burndown from board data | eight increments in two days; no board | **not met** |
| NFR-ORG-02 | Python 3.12 + FastAPI; React + React Flow | yes | met |
| NFR-EXT-01 | Synthetic or public de-identified data | synthetic only | met |

: Table 16.1 — Every NFR, measured.

## The Closure fix: NFR-ROB-01

Checking each NFR against what its test actually reproduces (Section 18 of the plan) found one gap.
NFR-ROB-01 says that with the ML service *down*, triage continues through the fallback within two
retries. The engine retried only when a service *answered* with a failure. A stopped service never
answers, so its request waited in the queue and the case waited with it. The test counted as
evidence used a running ML service with no model installed, which answers with a failure: a
different situation.

The fix (decision 0008) gives every automated task that has a retry policy or a fallback an
**answer timeout** (30 s by default, `retry.timeoutS` per task, 10 s in the clinical Triage). The
engine schedules a timer with each request; if the token still waits on the same attempt when it
fires, the silence counts as a temporary failure, and the normal order follows: retry with backoff,
then the fallback, then compensation. A late answer is ignored, as any late reply is (I1). The timer
uses the engine's persisted timer table, so it survives restarts, and its due time comes from the
request event, so replay stays exact (I3). New tests prove the unanswered sequence in the engine and
run the whole hospital with no ML service at all. The lesson is in chapter 14: "met" must mean that
the test reproduces the requirement's situation.

## The professor's requirements

`docs/closure/acceptance.md` checks every row of the requirements table (P1–P23, E1–E5) against the
delivered system. In summary: 23 rows are met; P5 and P6 (microservices deployed by Docker,
event-driven through RabbitMQ) are met in design and in the in-process runtime, but their Docker and
RabbitMQ implementations have not run against live daemons; P17 lacks burndown charts; P14 (approval
before implementation) and P23 (explaining all generated logic) can only be shown by the author, not
by the repository.

## Limitations

1. **Docker and RabbitMQ.** The measuring machine had no running Docker daemon throughout. The
   Compose start, the RabbitMQ bus, the Docker runtime and the engine's performance across a real
   broker and PostgreSQL are therefore unverified; every result here comes from the in-process
   runtime and SQLite. The adapters are small and behind interfaces that the tests exercise with
   fakes, but "small" is not "tested".
2. **Synthetic data.** The urgency model is trained on synthetic data (risk R6). Its pipeline,
   calibration and decision rule are real; its accuracy figures are not clinical evidence.
3. **The calendar.** The increments were built in two days, not sixteen weeks. Scrum's structure was
   kept; its time-boxes and the feedback they give were not. No burndown exists (NFR-ORG-01).
4. **Alpha test.** The usability target (SUS ≥ 70) is unmeasured until 3–5 classmates take the test.
5. **Security limits.** A compromised container inside the network could forge identity headers
   (mutual TLS or signed internal tokens would close this); the refresh token lives in
   `sessionStorage`, not an `httpOnly` cookie; the patient-data key cannot be rotated yet.
6. **Modelling limits of the simulator.** Escalation and task failures are not simulated, and a
   person's work is non-preemptive. The advisor is greedy and matched the optimum only on the small
   case where the optimum could be computed.
7. **No case cancellation.** "Cancelled" exists as a final status, but no action cancels a whole case.
8. **Smaller plan items.** The final audit (`docs/closure/acceptance.md`) found plan items no story
   covered. Five were then built (decision 0009): structured JSON logs with case ids, HTTPS at the
   web server, Grafana, the simulator's urgency mix from the training data, and Playwright browser
   tests. HTTPS and Grafana are configured and tested for consistency but, like all Docker parts,
   not seen running. Still missing: Testcontainers, per-sprint review videos and task boards. The
   model is trained by a script rather than a notebook, and three REST routes carry other names than
   in the plan's table.

## Ethics

The platform is decision support, not a medical device. Three design choices follow. A nurse
confirms every urgency level, and changing the model's suggestion requires a reason that is logged,
which keeps the human accountable and the model auditable. Safety rules in the pathway (oxygen,
blood pressure, NEWS2, low confidence) send a patient to urgent review whatever the model says. The
model's decision rule prefers over-triage to under-triage (urgent recall 0.90), because under-triage
harms patients. On privacy: no real patient data is used; identifiers are encrypted; events and
alerts carry a record number, never a name; logs carry case ids. A deployment with real data would
also need a data-protection impact assessment and clinical validation of the model on local data.

## Maintenance and future work

Lehman's laws (*11 – Software evolution and maintenance*) predict that a system used in a real
environment must keep changing (continuing change) and grows more complex unless work is done to
reduce it (increasing complexity). AdaptiveCare Flow is built for the first law: most clinical
changes are *pathway* changes, which become new verified versions without touching code, and new task
types plug in as services. Against the second law it has its complexity limit, strict typing, a
coverage floor and decision records. Further work, by maintenance type:

- **Corrective**: run and fix the Docker and RabbitMQ paths; add the access test for NFR-SEC-04.
- **Adaptive**: train on the KTAS file, then validate on local data; HL7 FHIR import of patients.
- **Perfective**: migrate running cases to a new version when it is safe (`MIG-01`), which needs a
  state-mapping check that the verifier could provide; simulate escalation and task failures; case
  cancellation; mutual TLS between services; key rotation for patient data; an `httpOnly` refresh
  cookie.
- **Preventive**: schema migrations instead of tables created at start-up (a schema change in this
  project meant recreating development databases).

## Lessons learned

1. **One semantics, three algorithms.** Putting the token rules in one library before anything else
   was the decision that paid most. The verifier, simulator and engine never disagreed about what a
   pathway means, and property-based tests on that one library protected all three.
2. **Purity makes reliability testable.** Because `Case.apply` has no clock and no I/O, crash, replay
   and duplicate tests were simple to write and fast to run. Every reliability property became an
   ordinary test.
3. **Tests that cannot fail are the AI's favourite.** The most dangerous AI output was not wrong code
   but a plausible test that proved nothing. Reading *what a test proves* mattered more than its colour.
4. **Measure against the requirement's own situation.** NFR-ROB-01 was "met" for a whole sprint on a
   test that simulated something else.
5. **The calendar is part of the process.** AI assistance made the scope feasible but removed the
   weeks over which Scrum gives feedback. A real project should keep the time-boxes even when the code
   comes faster, and use them for what the AI cannot do: users, data and operations.

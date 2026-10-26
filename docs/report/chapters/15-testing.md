# Testing and quality

## Results per test stage

The test plan follows the three stages of the course slides (*10 – Software testing*): development
testing, release testing and user testing, plus a special test that proves each algorithm.

| Stage | What is tested | How | Result |
|-------|----------------|-----|--------|
| Development: unit | Every token rule; the condition parser with partition and boundary values; each algorithm's functions; task settings | pytest, Hypothesis; test-first for pathway-core | pass |
| Development: component | Each service with its own database and the in-memory bus | pytest, FastAPI test client, SQLite | pass |
| Development: system | The services together, end to end | in-process system tests, every message delivered twice; Playwright in Chrome against the running platform | 8 system tests and 3 browser tests pass; the Compose and RabbitMQ run is open |
| Release: requirements-based | One automated test per acceptance criterion, named by story or NFR ID | traceability in appendix A | every story has a test |
| Release: scenario | Triage, Assessment and Visit end to end | `tests/system/test_clinical_pathways.py` | pass |
| Release: performance | The NFR-PERF targets | timed tests, engine load test | all four met (chapter 16) |
| Release: stress | Load until the system fails | `scripts/load_test.py` | saturates between 400 and 800 requests/s (below) |
| User: alpha | 3–5 classmates in the five roles, SUS questionnaire | `docs/alpha-test/` | **not yet run** |
| User: acceptance | The professor's requirements, row by row | `docs/closure/acceptance.md` | chapter 16 |
| Inspections | Code against the checklist; UML against the code | review per increment; `docs/closure/uml-check.md` | 16 diagrams updated and 3 regenerated in Closure |
| Regression | The whole suite | before every tag | 648 Python, 13 web unit and 3 browser tests pass |

: Table 15.1 — Results by test stage.

### Special tests per algorithm

| Algorithm | Test | What it proves | Result |
|-----------|------|----------------|--------|
| Verifier | A catalogue of 12 pathways with known answers | Every error type is found | pass |
| Verifier | Property-based: generated block-structured pathways are SAFE; changing one join's type is detected; every counterexample replays | The checker is right on thousands of inputs, not only hand-picked ones | pass |
| Engine | Fault injection: duplicates, reordering, concurrent join inputs, crashes at two points | Invariants I1–I5 | pass |
| Engine | Replay of 1,000 random cases | Determinism (I3) | pass |
| Engine | An ML service that never answers | NFR-ROB-01 (Closure) | pass |
| Simulator | Erlang C, Little's law, extreme cases, same seed → same result | The simulator computes correct numbers | 92/100 inside the interval |
| Advisor | Exhaustive search on a small case | How close greedy gets to the best | gap 0 |
| Model | Stratified 5-fold cross-validation and a held-out test set | The model's quality, measured honestly | chapter 12 |

: Table 15.2 — Special tests per algorithm.

### Test growth

{{chart growth "Figure 15.1 — Python test functions and code lines at each sprint tag."}}

Test functions grew from 53 to 267 across the tags, in step with the code. Parametrised tests make
the executed count larger: 648 Python tests, 13 web unit tests and 3 browser tests run in the final suite.

### Coverage

The NFR asks for at least 80% statement coverage on the core packages, with branch coverage
reported (NFR-MNT-01). Table 15.3 gives both for every package.

| Package | Statements | Statement coverage | Branch coverage |
|---------|-----------:|-------------------:|----------------:|
| pathway-core | 622 | **98.7%** | 95.7% |
| verifier | 354 | **98.9%** | 96.4% |
| engine | 618 | **92.6%** | 80.0% |
| simulator | 671 | **97.0%** | 91.8% |
| worklist | 579 | 97.1% | 88.5% |
| patient | 300 | 97.7% | 85.4% |
| designer | 238 | 92.9% | 67.6% |
| auth | 204 | 94.6% | 76.3% |
| gateway | 123 | 98.4% | 100% |
| ml | 158 | 91.8% | 80.8% |
| scores | 87 | 97.7% | 80.0% |
| service-metrics | 134 | 100% | 100% |
| deployer | 325 | 82.2% | 58.3% |
| care-events | 300 | 78.7% | 71.4% |
| **Total** | **4,713** | **94.3%** | **86.5%** |

coverage.py's single combined figure (statements and branches together), which the CI gate checks
against 80%, is 92.9%.

: Table 15.3 — Coverage by package (core packages in bold).

The two lowest are explained by the missing Docker daemon: `care-events` contains the RabbitMQ
adapter and `deployer` the Docker runtime, neither of which has run against a live daemon.

### Stress test

`scripts/load_test.py` sends read-only nurse traffic (80% worklist, 20% patient search) through the
gateway of the development stack, at rising rates, 5 s per step, until more than 5% fail or p95
exceeds 2 s.

| Target/s | Achieved/s | p50 ms | p95 ms | Errors |
|---------:|-----------:|-------:|-------:|-------:|
| 10 | 10 | 11 | 14 | 0% |
| 25 | 25 | 10 | 12 | 0% |
| 50 | 50 | 5 | 7 | 0% |
| 100 | 100 | 4 | 5 | 0% |
| 200 | 200 | 3 | 3 | 0% |
| 400 | 400 | 2 | 2 | 0% |
| 800 | 237 | 918 | 2,900 | 0% |

: Table 15.4 — Stress test through the gateway (development stack).

The stack saturates between 400 and 800 requests per second: throughput falls to 237 per second
and p95 reaches 2.9 s, but no request fails. The development stack runs every service in one Python
process, and the load generator shares the machine, so this is a lower bound for Compose, where
each service has its own process.

## Static quality

- **Complexity** — radon reports no function with cyclomatic complexity above 10 in production
  code (NFR-MNT-02). Functions that crossed the limit while being written were split before their
  increment was tagged (in Sprints 6 and 7 alone: `features`, `BedService._reserve`,
  `Exporter.decision`, `Metrics.summary`, `Monitor._record`).
- **Types** — `mypy --strict` passes on 73 source files.
- **Style** — ruff (pycodestyle, pyflakes, bugbear, bandit rules, import order, complexity) and
  ruff format pass on every Python file; TypeScript type-checks with `tsc --noEmit`.
- **Security** — bandit reports no issue in production code; pip-audit finds no known
  vulnerability in any service's requirements (NFR-SEC-06).

## The software qualities

The course's *2 – Software qualities* deck lists the qualities below. Table 15.5 gives the
evidence for each.

| Quality | Evidence |
|---------|----------|
| Correctness | Pathways proven sound or disproved by counterexamples (Algorithm 1); the property-based tests prove the verifier itself on generated inputs |
| Reliability | Invariants I1–I5 proven under fault injection; outbox; replay; snapshots |
| Robustness | Retries, answer timeouts, fallbacks and compensation; a model that is down or missing still lets triage finish (NFR-ROB-01) |
| Performance | Four measured targets met with a wide margin; performance of pathways predicted by simulation (Algorithm 3) |
| Usability | Errors on the canvas with a step-by-step replay; intervals on every simulated figure; the SUS test is still open |
| Verifiability | Every requirement has a test (appendix A); deterministic engine and simulator (same input, same output) |
| Maintainability | 94.3% statement and 86.5% branch coverage; complexity ≤ 10; strict typing; decision records; diagrams checked against code |
| Reusability | One `pathway-core` for three algorithms; `care-events` and `service-metrics` shared by the services |
| Portability | Docker images for every service; the development stack runs without Docker (the Compose start is unverified) |
| Interoperability | REST and JSON events with a written contract; a new task type plugs in by subscribing to a routing key (CLN-04) |
| Security | Permission matrix tested for every route and role; encrypted identifiers; least privilege |

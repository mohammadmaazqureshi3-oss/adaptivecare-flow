# Measured NFR results (Sprint 7)

Measured on 2026-10-26 on the development laptop (Apple silicon, macOS, Python 3.13), with
SQLite and the in-memory bus (Docker was not available; see "Not measured").

| NFR | Target | Measured | How | Result |
|-----|--------|----------|-----|--------|
| NFR-PERF-01 | Verifier ≤ 2 s for 30 nodes, 4 parallel branches | 0.04 s | `test_nfr_perf_01_…` | met |
| NFR-PERF-02 | Engine event p95 ≤ 200 ms at 50 events/s | p95 3 ms, max 4 ms, at 250 events/s (50 registrations/s plus replies) | `services/engine/tests/test_performance.py` | met |
| NFR-PERF-03 | 30 replications × 7 days, 20 nodes ≤ 60 s | 5.0 s | `test_nfr_perf_03_…` | met |
| NFR-PERF-04 | ML prediction p95 ≤ 100 ms | 11 ms | `test_nfr_perf_04_…` | met |
| NFR-REL-01..03 | No double change, resume after crash, no lost task | pass | fault-injection tests I1–I5 (Sprints 3–4) | met |
| NFR-ROB-01 | ML down → fallback within 2 retries | pass: 3 unanswered attempts, then manual triage | `test_nfr_rob01_…` (engine, clinical system test with no ML service); live in the dev stack with `DEV_WITHOUT=ml`: manual triage 33.5 s after the vital signs | met after the Closure fix (decision 0008) |
| NFR-SEC-01/02 | Tokens; permission matrix | every rule × every role | `test_nfr_sec02_permission_matrix` (gateway) | met |
| NFR-SEC-05 | Name and birth date encrypted; key outside the repository | raw-database inspection finds no name or date | `test_nfr_sec05_…` | met |
| NFR-SEC-06 | No high findings (bandit, pip-audit) | 0 bandit issues; pip-audit: no known vulnerabilities in any requirements file | CI security job | met |
| NFR-MNT-01 | ≥ 80% coverage | 94.3% statements, 86.5% branches (92.9% combined) | `pytest --cov` | met |
| NFR-MNT-02 | Complexity ≤ 10; ruff, mypy | radon: no function above 10; ruff and mypy --strict clean | CI | met |
| NFR-MNT-03 | New task type without engine change | NEWS2 service (CLN-04) | `services/scores`, clinical system tests | met |
| NFR-USE-02 | SUS ≥ 70 in an alpha test | not yet run | `docs/alpha-test/` | open |

## Stress test ("load until the system fails")

`scripts/load_test.py` through the gateway of the development stack (all services in one
Python process), read-only nurse traffic (80% worklist, 20% patient search), 5 s per step:

| Target/s | Achieved/s | p50 ms | p95 ms | Errors |
|---------:|-----------:|-------:|-------:|-------:|
| 10 | 10 | 11 | 14 | 0% |
| 25 | 25 | 10 | 12 | 0% |
| 50 | 50 | 5 | 7 | 0% |
| 100 | 100 | 4 | 5 | 0% |
| 200 | 200 | 3 | 3 | 0% |
| 400 | 400 | 2 | 2 | 0% |
| 800 | 237 | 918 | 2900 | 0% |

The stack saturates between 400 and 800 requests per second: throughput falls to 237/s and
p95 reaches 2.9 s, but nothing fails. The load generator runs on the same machine and
shares its CPU, so the true limit of the services alone is somewhat higher. In Compose
each service has its own process, so this is a lower bound.

## Not measured (Docker unavailable on the measuring machine)
- NFR-PERF-02 over RabbitMQ and PostgreSQL (the in-process figure above has no network hop).
- NFR-POR-01, the one-command start on a fresh machine.
- NFR-SEC-04 runtime check (the Compose file is inspected; the access test from another
  container needs Docker).

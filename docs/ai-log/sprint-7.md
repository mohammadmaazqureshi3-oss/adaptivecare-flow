# Prompt log — Sprint 7: hardening and measurement

Sprint goal: measured NFR results; alpha usability test ready to run.
Stories: CLN-04, WRK-03, MON-01, MON-02, MON-03, SIM-05; NFR-SEC-05, NFR-PERF-02, NFR-MNT-03,
NFR-USE-02 kit. UML: U31, U32 final; U28 regenerated for Triage v3. Decision 0007.

## Produced
- **NFR-SEC-05** `patient/vault.py`: Fernet encryption of name and birth date (key from
  `PATIENT_DATA_SECRET` via HKDF), HMAC blind index for word-prefix search and the duplicate
  check; raw-database inspection test; the service refuses to start without a secret.
- **MON-01/02** `worklist/monitor.py`: a second consumer bound to `#` keeps case summaries
  and every case's timeline; patient journey across the chained pathways; dashboard
  (active cases, queues, waits, missed deadlines; tasks gain `claimed_at`).
- **WRK-03** `worklist/alerts.py`: alert contacts per role, deliveries queued with the
  notification (outbox), sender thread with retries; SMTP + STARTTLS, HTTP SMS gateway, log.
- **MON-03** `packages/service-metrics`: per-route-template request metrics in Prometheus
  format in all ten services; gateway `/monitor/services`; Prometheus Compose profile.
- **CLN-04 / NFR-MNT-03** `services/scores`: NEWS2 (RCP 2017, scale 1) as a new task type;
  Triage v3 uses it with a manual fallback. The engine's token rules, case and service code
  are unchanged (`git diff sprint-6 -- services/engine/engine` shows only the three-line
  metrics hook of MON-03 in `main.py`, nothing for NEWS2).
- **SIM-05** `simulator/compare.py` + comparison view: intervals side by side, "better"
  only when the 95% intervals do not overlap, changed settings listed.
- Web: Monitoring (dashboard, cases with timeline, services), Alerts with deliveries and
  contacts, run comparison on the Simulate page; admins land on Monitoring.
- Measurement: `test_performance.py` (NFR-PERF-02), `scripts/load_test.py` (stress),
  `scripts/sus_score.py` + `docs/alpha-test/` (NFR-USE-02), `docs/measurements/nfr-results.md`.

## Where the AI was wrong and testing caught it (for the report, Section 14 item 4)
1. **A fallback test that could never pass.** The first CLN-04 system test ran Triage
   without the scores service and expected the manual NEWS2 task. Nothing answers a request
   to a service that is not there, so the engine waits (the request stays queued); the
   fallback only follows failures. The test now uses a scores service that keeps failing.
   The finding is recorded in decision 0007 item 8.
2. **Scrapes counted as traffic.** The metrics middleware excluded `/metrics` by route
   template, but routes added with `add_route` do not set it, so scrapes were counted.
   Caught by the token test (expected 0 requests, got 3); it now excludes by path.
3. **`@app.middleware` on a plain Starlette type** passed the tests (the apps are FastAPI)
   but failed mypy --strict; replaced by `add_middleware(BaseHTTPMiddleware, …)`.
4. **A clock in the past.** The alert retry test used a fixed clock earlier than the real
   creation time of the delivery, so nothing was due. It now starts from the real time.
5. **An overclaim in this log.** The first draft said the engine had no change at all in
   Sprint 7; `git diff` showed the MON-03 metrics hook in `engine/main.py`. Reworded to
   what is true: no engine change for the new task type.
6. **Prometheus with the Docker socket.** The first configuration discovered engine
   containers through the Docker socket, which would break least privilege (NFR-SEC-04).
   Caught in review against the NFR table; engines are not scraped.
7. bandit flagged an empty-string password default (B107) in the email channel; now `None`.

## Measured
See `docs/measurements/nfr-results.md`. NFR-PERF-01 0.04 s, NFR-PERF-02 p95 3 ms at
250 events/s, NFR-PERF-03 5.0 s, NFR-PERF-04 11 ms; coverage 92.8%; pip-audit clean.
Stress: the single-process dev stack holds 400 requests/s (p95 2 ms) and saturates
before 800 (237/s achieved, p95 2.9 s, no errors).

Browser: as admin, Monitoring showed the dashboard, the case timeline (vital signs →
NEWS2 13 high → ML level 2 → urgent confirmation) and every service healthy; an alert
contact was added. As designer, two runs (2 vs 4 nurses) were compared: 8 of 14 figures
differ beyond their intervals, all in favour of 4 nurses.

## Not done
- The alpha test itself (needs 3–5 classmates): script, form and scorer are ready.
- Docker-based checks (Compose start, RabbitMQ, the Docker runtime) remain open.

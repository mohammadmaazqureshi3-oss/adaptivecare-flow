Sprint 7 plan (hardening and measurement). Backlog from the plan: CLN-04, WRK-03, MON-01..03, SIM-05, NFR tests.

Design chosen after reading the code:
- MON-01/02: worklist gets a `monitor` queue bound to `#`; it records every case event (timeline) and case summaries (pathway, version, patient, status, start/end). Dashboards (active cases, waits, missed deadlines) come from summaries + tasks (add `claimed_at`). Separate inbox key per consumer, since `first_time` shares one inbox table per database.
- MON-03: request count/latency `/metrics` middleware in care-events; gateway `/monitor/services` combines health and metrics; Prometheus as a Compose profile.
- WRK-03: worklist `alert_contacts` (role, email|sms, address, admin-managed) and a `deliveries` table sent by a worker (SMTP; SMS via an HTTP gateway; log sender in dev) with retries.
- CLN-04 / NFR-MNT-03: new `services/scores` service answering `TaskRequested.News2Score` (NEWS2 from the vital signs), used by Triage v3; no engine change.
- SIM-05: `GET /simulations/compare?a=&b=` (metric, both intervals, difference, intervals overlap) and a compare view on the Simulate page.
- NFR-SEC-05: patient name and birth date encrypted with Fernet (`cryptography`), key derived from `PATIENT_DATA_SECRET`; HMAC blind index of name-word prefixes for search and duplicate check; raw-database inspection test.
- NFR-SEC-02: generated allowed/denied test for every rule and role. NFR-PERF-01/02/03 timed tests + a locustfile; pip-audit; alpha-test kit (script, SUS form, scoring script); U31/U32 final; decision 0007.

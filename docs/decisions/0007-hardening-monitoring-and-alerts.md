# 0007 — Hardening: encryption, monitoring, alerts, a new task type

**Status:** accepted · **Sprint:** 7 · **Stories:** CLN-04, WRK-03, MON-01..03, SIM-05; NFR-SEC-05, NFR-PERF-02, NFR-MNT-03, NFR-USE-02

## Context
Sprint 7 hardens the platform and measures it. Several stories needed a place to live and
a way to talk to the rest of the system without breaking the event contract.

## Decisions
1. **Patient identifiers encrypted at rest (NFR-SEC-05).** Name and date of birth are
   Fernet tokens (AES-128-CBC + HMAC-SHA256) with a key derived by HKDF from
   `PATIENT_DATA_SECRET`, which comes from the environment; the service refuses to start
   without it. Search and the duplicate check use a *blind index*: keyed hashes of each
   prefix of each name word, and of (name, birth date). Search becomes "start of any name
   word" instead of "anywhere in the name"; the index reveals which records share a prefix,
   never the letters. Changing the secret makes stored patients unreadable (no key rotation
   yet: a known limit).
2. **Case history from the bus (MON-01).** The worklist runs a second consumer, `monitor`,
   bound to `#`. It keeps a summary per case and a timeline of every event that leaves a
   service. Engines keep their own full log, but an engine is stopped when its version is
   retired; the monitor's record outlives it and spans all pathways. Cases are linked into
   a patient's journey by `patient_id`, so the engine needed no change. Duplicates are
   dropped by the unique event id in `case_events` (the shared inbox table belongs to the
   task consumer).
3. **Dashboard (MON-02)** is computed on request from the case summaries and the task table
   (new `claimed_at`): active and ended cases, queues per role, waits until a task is taken
   (mean, 90th percentile), missed deadlines and escalations.
4. **Alerts by email/SMS (WRK-03).** The engine already sends `NotificationRequested` on
   every escalation. The worklist turns each into one delivery per active contact of that
   role, in the same transaction (an outbox), and a sender thread delivers with retries
   (30 s doubling, 5 attempts). SMTP with STARTTLS for email, an HTTP gateway for SMS; in
   development, the log. Messages carry the task and the record number, never a name.
5. **Metrics (MON-03)** come from a small shared package, `service-metrics`: request counts,
   errors and a latency histogram per route *template* (ids never become labels), served
   as Prometheus text at `/metrics` and as JSON for the admin page; optional
   `METRICS_TOKEN`. The gateway combines every service's health and metrics. Prometheus is
   an optional Compose profile; it does not scrape engines, because finding them needs the
   Docker socket, which only the deployer may reach (NFR-SEC-04).
6. **A new task type as a new service (CLN-04, NFR-MNT-03).** `scores` answers
   `TaskRequested.News2Score` with NEWS2. Triage v3 calls it after the vital signs (which now
   include oxygen), falls back to a nurse after two failed retries, and adds `news2 >= 7` to
   the red flags. No engine code changed for this.
7. **Scenario comparison (SIM-05)** calls one scenario better for a figure only when the two
   95% intervals do not overlap. That is conservative: overlapping intervals can still
   differ. The comparison says "no clear difference" rather than guessing.
8. **Service tasks wait for their service.** *(Superseded by decision 0008: automated tasks
   now have an answer timeout.)* With a durable queue, a request to a service
   that is down waits until it returns; the fallback runs only after the service answers
   with failures. A deadline-based timeout for service tasks would need an engine change
   and is left for later.

## Consequences
The event contract gains no new types. New REST routes are listed in `contracts/events.md`
and the gateway's permission matrix. Dev databases of the patient and worklist services
must be recreated, since there are no migrations.

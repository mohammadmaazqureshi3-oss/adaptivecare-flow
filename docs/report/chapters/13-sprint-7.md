# Sprint 7: hardening and measurement

## Goal

*Measured NFR results; the alpha usability test ready to run.*

## Sprint backlog

| Story | Points | Summary |
|-------|-------:|---------|
| CLN-04 | 3 | A new task type is added as a new service without changing the engine |
| WRK-03 | 3 | A charge nurse or manager gets an email or SMS alert when a task escalates to them |
| MON-01 | 3 | An admin views any case's full history |
| MON-02 | 5 | A manager sees dashboards of active cases, waits and missed deadlines |
| MON-03 | 3 | An admin sees service health and metrics |
| SIM-05 | 3 | A designer compares two scenarios side by side |
| | **20** | plus NFR-SEC-05, the performance and stress tests, and the alpha-test kit |

## User stories and acceptance criteria

- **CLN-04 / NFR-MNT-03** — *Given* a new service answering `TaskRequested.News2Score`, *when* a pathway
  names it in a task, *then* cases use it with no change to the engine's code.
- **WRK-03** — *Given* an escalation to the charge nurse, *then* every active contact of that role
  receives an email or SMS once, even if the escalation event arrives twice; failed sends are
  retried and then shown as failed.
- **NFR-SEC-05** — *Given* a copy of the patient database, *then* no name or birth date can be read
  from it; *given* another key, the service can neither read nor find the patients.

## Design

### Patient identifiers encrypted at rest (NFR-SEC-05)

Name and birth date are stored as Fernet tokens (AES-128-CBC with an HMAC-SHA256 tag). The key is
derived by HKDF from `PATIENT_DATA_SECRET`, which comes from the environment; the service refuses to
start without it. Encrypted values cannot be searched, so search and the duplicate check use a
**blind index**: keyed hashes (HMAC) of every prefix of every name word, and of (name, birth date).
Search becomes "the start of any name word" — `ada lo` finds Ada Lovelace — instead of "anywhere
in the name". The index reveals which records share a prefix, never the letters (decision 0007).

### Case monitor and dashboard (MON-01, MON-02)

The worklist runs a second consumer, `monitor`, bound to every routing key (`#`). It keeps a
summary per case (pathway, version, patient, status, start and end) and a timeline of every event
that leaves a service: requests, completions with the outputs and who completed them, overrides
with their reasons, failures, escalations, undo steps. The engine keeps its own full log, but an
engine stops when its version retires; the monitor's record outlives it and spans all pathways.
Cases are linked into a patient's **journey** (Triage → Assessment → Visit) by record number, so the
engine needed no change. The dashboard is computed on request: active and ended cases, queues per
role with the oldest wait and the overdue count, waits until someone takes a task (mean and 90th
percentile, from a new `claimed_at`), and missed deadlines and escalations.

### Email and SMS alerts (WRK-03)

The engine already sends `NotificationRequested` on every escalation. The worklist turns each into
one delivery per active contact of the role, in the same transaction as the notification — an
outbox, so no alert is lost between the two. A sender thread delivers them with retries (30 s
doubling, 5 attempts), by SMTP with STARTTLS or through an HTTP SMS gateway; in development they go
to the log. Messages carry the task and the record number, never a name.

### Service metrics (MON-03)

A small shared package, `service-metrics`, gives every service request counts, error counts and a
latency histogram per **route template** (`/tasks/{task_id}/claim`, so ids never become labels), in
Prometheus format at `/metrics` and as JSON at `/metrics.json`, plus service-specific gauges such as
open tasks or running cases. The gateway combines every service's health and metrics for the admin.
Prometheus (with Grafana, added in Closure) is an optional Compose profile. It does not scrape engines, because finding them needs
the Docker socket, which only the deployer may reach (NFR-SEC-04).

### A new task type: NEWS2 (CLN-04)

`services/scores` answers `TaskRequested.News2Score` with the NEWS2 score [7]: seven observations
banded into 0–3 points each (Table 13.1), a total, and a risk (7+ high, 5–6 medium, any single 3
low-medium, else low). Missing observations are a permanent failure; anything unexpected is
temporary. Triage v3 calls it after the vital signs (which now include oxygen), falls back to a nurse
"Calculate NEWS2 by hand" task after two failed retries, and adds `news2 >= 7` to the red flags. The
engine's token rules, case and service code did not change for this; the engine's only Sprint 7
change was the three-line metrics hook of MON-03.

| Observation | 3 | 2 | 1 | 0 | 1 | 2 | 3 |
|-------------|---|---|---|---|---|---|---|
| Respiration rate | ≤ 8 | | 9–11 | 12–20 | | 21–24 | ≥ 25 |
| SpO₂ (scale 1) | ≤ 91 | 92–93 | 94–95 | ≥ 96 | | | |
| Air or oxygen | | oxygen | | air | | | |
| Systolic pressure | ≤ 90 | 91–100 | 101–110 | 111–219 | | | ≥ 220 |
| Pulse | ≤ 40 | | 41–50 | 51–90 | 91–110 | 111–130 | ≥ 131 |
| Consciousness | | | | alert | | | V, P, U or new confusion |
| Temperature | ≤ 35.0 | | 35.1–36.0 | 36.1–38.0 | 38.1–39.0 | ≥ 39.1 | |

: Table 13.1 — NEWS2 bands as implemented (`services/scores/scores/news2.py`).

### Scenario comparison (SIM-05)

Two finished runs are compared figure by figure: both 95% intervals, the difference of the means, and
whether the intervals overlap. One scenario is called better only when they do not; overlapping
intervals are reported as "no clear difference" rather than guessed. Whether lower or higher is
better is known per metric (waits and the share of patients beyond a target's limit lower,
patients completed higher, utilisation neither). The changed
settings are listed, so the reason for a difference is visible.

### Final architecture

{{uml U31}}

## Implementation notes

The web app gained a Monitoring area (a dashboard; cases with filters, a timeline and the patient's
journey; services with health and metrics), alert contacts and the delivery log on the Alerts page,
and a comparison view on the Simulate page. Admins now land on Monitoring. `scripts/load_test.py`
is a stress test through the gateway; `scripts/sus_score.py` scores the alpha test.

## AI usage

1. **A fallback test that could never pass.** The first CLN-04 system test ran Triage without the
   scores service and expected the manual task. Nothing answers a request to a service that is not
   there, so the case waited. The test now uses a scores service that keeps failing. This was the
   first sign of the NFR-ROB-01 gap fixed in Closure (decision 0008).
2. **Scrapes counted as traffic.** The metrics middleware excluded `/metrics` by route template, but
   routes added with `add_route` set none; a token test (expected 0 requests, got 3) caught it.
3. **A middleware decorator** that only FastAPI offers passed the tests but failed `mypy --strict`.
4. **A clock in the past** made an alert-retry test find nothing due.
5. **An overclaim in the prompt log** ("no engine change at all") corrected after `git diff` showed
   the metrics hook.
6. **Prometheus with the Docker socket** would have broken least privilege; caught in review against
   the NFR table.
7. bandit flagged an empty-string password default in the email channel.

## Tests and results

- NFR-SEC-05: a raw-database inspection finds no name or date; another key can neither read nor find
  patients; the service needs a strong secret.
- MON-01/02: timeline, journey, filters, dashboard figures on hand-made data, the waits recorded at
  claim. WRK-03: emailed once despite a duplicate event, retried then failed, inactive contacts skipped,
  addresses validated, SMTP with STARTTLS and login, SMS with a bearer token.
- MON-03: route templates not paths, the token, the gateway's overview, a service shown as down.
- CLN-04: every NEWS2 band boundary, the risk thresholds, missing data named, the service's replies;
  the clinical system test checks that NEWS2 reaches the confirmation.
- SIM-05: direction per metric, separate and overlapping intervals, changed settings, the endpoint.
- **NFR-PERF-02**: 50 registrations per second for 6 seconds with simulated workers answering — about
  250 events per second — gives p50 1 ms, **p95 3 ms**, max 4 ms (target p95 ≤ 200 ms at 50/s).
- **Stress**: chapter 15. **pip-audit**: no known vulnerabilities in any requirements file.

{{chart nfr "Figure 13.2 — Performance NFRs as a share of their targets."}}

Test functions at the tag: 267 Python and 13 web.

## Review and retrospective

**Review** (browser): as admin, the dashboard; a case's timeline (vital signs → NEWS2 13, high → model
level 2 → urgent confirmation); every service healthy; an alert contact added. As designer, two runs
compared (2 vs 4 nurses): 8 of 14 figures differ beyond their intervals, all in favour of 4 nurses.
**Keep:** measuring against the NFR table, not against a feeling of "fast enough". **Stop:** writing
"met" before the test truly reproduces the NFR's situation (NFR-ROB-01). **Try:** run the Docker
path and the alpha test before the presentation (chapter 16).

# Architecture

The architecture is described with Kruchten's 4+1 views [13], as the course slides
(*9 – Software architecture*) recommend. Table 5.1 maps the views to diagrams; the logical-view
class diagrams appear in the sprint chapters where those classes were designed.

| View | Shows | Diagrams |
|------|-------|----------|
| Logical | The main abstractions | Class U04, U05 (chapter 7), U12 (chapter 8), U18 (chapter 9) |
| Process | Run-time behaviour and concurrency | Sequence U08, U13, U20, U21, U24, U27 |
| Development | How the code is organised | Package U06, component U31 (this chapter) |
| Physical | Containers and the host | Deployment U32 (this chapter) |
| Scenarios | The use cases that tie the views together | Use case U01–U03 (chapter 4) |

: Table 5.1 — The 4+1 views and their diagrams.

## Architectural styles

All the styles below come from the course slides:

- **Client-server** — the web app is a client of one server, the API gateway.
- **Service-oriented** — eleven services, each owning one capability and its own data.
- **Publish-subscribe and implicit invocation** — at run time services do not call each other;
  they publish events to one topic exchange, and whoever is bound receives them.
- **Interpreter** — the engine does not contain any pathway; it interprets the pathway model
  it is given. Changing clinical logic means editing a model, never code.
- **Repository** — each service owns a schema in one PostgreSQL server (database per service);
  no service reads another's tables.
- **Layered** — inside each service: API (FastAPI routes), domain (pure functions such as
  `Case.apply`), persistence (SQLAlchemy).

## Services

{{uml U31}}

| Service | Job | Data it owns | Talks by |
|---------|-----|--------------|----------|
| gateway | Single entry; checks the token and role on every route; proxies; service health and metrics overview | — | REST |
| auth | Users, roles, login, tokens, login log | users, login_log | REST |
| designer | Pathways and versions; Verify and Publish; condition checks | pathways, versions | REST, events (deploy status) |
| verifier | Algorithm 1 (stateless) | — | REST |
| simulator | Algorithm 3; long jobs in the background; comparison | jobs | REST |
| deployer | PIM → PSM; starts, drains and stops engines; the only service with Docker access | deployments | REST, Docker Engine API, events |
| engine (one per deployed version) | Algorithm 2 | case_events, cases, timers, snapshots | events |
| worklist | Tasks for people, overrides, notifications, email/SMS alerts, case monitor and dashboard | tasks, overrides, notifications, alert_contacts, deliveries, case_summaries, case_events | REST, events |
| patient | Patients (encrypted), beds; the `BedService` worker | patients, patient_terms, beds | REST, events |
| ml | Urgency prediction (`PredictUrgency`) | model file | events |
| scores | NEWS2 (`News2Score`), added in Sprint 7 | — | events |

: Table 5.2 — Services.

**Shared libraries.** `pathway-core` holds the pathway model, the token rules, the task settings
and the condition language. The verifier, the simulator and the engine all use it, so the
semantics exist once. `care-events` holds the event envelope, the bus (in-memory and RabbitMQ),
and the outbox and inbox. `service-metrics` gives every service the same `/metrics`.

{{uml U06}}

## Events

Every event carries one envelope: `event_id`, `type`, `case_id`, `token_id`, `pathway`, `version`,
`attempt`, `timestamp`, `target` and `payload`. Routing keys follow three shapes (decision 0003):

- **requests** `<Type>.<target service>`, e.g. `TaskRequested.worklist`, `TaskRequested.PredictUrgency`;
- **replies** `<Type>.<pathway>.v<version>`, e.g. `TaskCompleted.triage.v4`; each engine binds
  `*.<pathway>.v<version>`, so replies never reach another version's engine;
- **broadcasts** the type alone, e.g. `PatientRegistered`, `CaseCompleted`, or an event a
  pathway's End announces, such as `TriageCompleted`.

Each consumer has its own queue and acknowledges a message only after committing its change, so
delivery is at least once. Every event derived from another has a deterministic id (uuid5 of
its inputs), so a duplicate input produces a duplicate id, which consumers drop. Appendix B
reproduces the full catalogue from `contracts/events.md`.

## Security design

- **Authentication** — bcrypt password hashes; HS256 JWT access tokens (15 minutes) and refresh
  tokens (8 hours); the role is re-read at refresh (NFR-SEC-01).
- **Authorisation** — the permission matrix in one file at the gateway, deny by default; the
  gateway forwards the identity in headers that services trust, because only the gateway's port
  is published (decision 0002) (NFR-SEC-02).
- **Separation of duties** — designers publish, only admins deploy (NFR-SEC-03).
- **Least privilege** — only the deployer mounts the Docker socket; Prometheus deliberately does
  not discover engines through it (NFR-SEC-04, decision 0007).
- **Minimum necessary data** — `PatientRegistered` carries the record number, age, sex, arrival
  mode and complaint, never a name or birth date. Alerts carry the record number, never a name.
- **Encryption at rest** — patient name and birth date are Fernet tokens; search uses a blind
  index of keyed hashes; the key comes from the environment (NFR-SEC-05, chapter 13).
- **Scans** — bandit and pip-audit in CI; gitleaks for secrets (NFR-SEC-06).

Known limits, stated in decision 0002 and chapter 16: a compromised container inside the network
could forge identity headers (mutual TLS or signed internal tokens would close this), and the
refresh token sits in `sessionStorage` rather than an `httpOnly` cookie.

## Data model

Each service owns a schema (diagram E1). There are no foreign keys across schemas; services refer
to each other's records by identifier (a record number, a case id, an email). The engine's schema
is created per deployed version (`engine_triage_v4`), so a retired version's history stays intact.

{{uml E1}}

## Deployment: from model to running engine

The course slides (*7 – Modelling*) describe model-driven architecture: a platform-independent
model (PIM) is transformed into a platform-specific model (PSM). Deployment does exactly that. The
published pathway JSON is the PIM; the deployer generates the engine's configuration — container
name, queue `engine.triage.v4`, schema `engine_triage_v4`, environment and health check — which is
the PSM. It then creates the schema, starts the container through the Docker Engine API (or, in
the development stack, an in-process engine), waits for the health check and publishes
`PathwayDeployed` (diagram U21, chapter 10). Undeploying drains the version: no new cases, and the container
stops when its last case ends.

{{uml U32}}

The platform starts with one command, `docker compose up --build` (NFR-POR-01). A development
stack (`scripts/dev.sh`) runs every service in one Python process with the in-memory bus, for
machines without Docker; it is what the measurements in this report were taken on.

## Conway's law

Conway's law predicts that a system's structure mirrors its team's communication [17]. A
one-person team gives no such pressure. The service boundaries here follow capabilities and data
ownership instead: who owns patient records, who owns tasks, who owns a running case. This is
noted as a limitation. In a real department, the boundary between the worklist (nursing) and the
patient service (registration and beds) would probably follow the organisation.

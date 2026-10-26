# 0009 — Closure additions: structured logs, HTTPS, Grafana, the urgency mix, browser tests

**Status:** accepted · **Phase:** Closure (final audit) · **Plan items:** C4-03, C4-06, Section 9,
Section 11, Section 14

## Context
The final audit (`docs/closure/acceptance.md`) found plan items that no backlog story covered.
Five could be built and tested on this machine.

## Decisions
1. **Structured logs (C4-06).** `service_metrics.logs` writes one JSON object per line: `ts`,
   `level`, `service`, `logger`, `msg`, `case_id`, and event fields when given. Event consumers
   (engine, worklist tasks and monitor, beds, ml, scores) run each event inside
   `case_context(event.case_id)`, so every line logged while handling it carries the case id,
   whatever module logs it. The engine logs one line per handled event. `instrument()` installs
   the handler, so every service has it; `LOG_FORMAT=text` gives plain lines.
2. **HTTPS (C4-03).** nginx serves the app on 443 (TLS 1.2/1.3, HSTS, nosniff, frame-deny,
   no-referrer, a content security policy) and redirects port 80. Without a mounted certificate,
   a start-up script makes a self-signed one inside the container; no key is kept in the image or
   the repository. Compose publishes 8443 (HTTPS) and 8080 (redirect).
3. **Grafana (Section 9, Should).** In the `monitoring` profile, provisioned with the Prometheus
   data source and one dashboard (services up, open tasks, pending alerts, request rate, p95 latency,
   server errors, slowest routes). Admin password from `.env`; anonymous access and sign-up off.
4. **Urgency mix (Section 11).** Training writes the class shares of its data to
   `services/simulator/simulator/urgency_mix.json`; the simulator uses them as the default mix,
   shows their source on `/health`, and falls back to the illustrative mix if the file is missing.
   Data flows one way at build time; there is no run-time link between the services.
5. **Browser tests (Section 14).** Playwright tests in `web/e2e/` drive the installed Chrome against
   the running platform: verification and replay, a patient through triage with NEWS2, the model
   and an override, and monitoring. A CI job runs them on Playwright's Chromium.

## Consequences
The structured logs, the mix and the browser tests run here and are tested. The HTTPS server and
Grafana could not be started without Docker; their configuration is checked by tests against the
code (certificate paths, scraped services, metric names) but has not been seen working.

# UML check against the code (Closure, Section 18)

Each diagram in `docs/uml/` was read against the code it describes on 2026-10-26.
"Updated" means the diagram was changed in Closure to match the final code.

| ID | Diagram | Checked against | Result |
|----|---------|-----------------|--------|
| U01 | Whole system (use case) | gateway permission matrix | Updated: charge nurse, beds, alerts, service health, comparison |
| U02 | Designer and admin (use case) | designer, simulator, worklist routes | Updated: managers simulate, SIM-05, alert contacts, new settings |
| U03 | Clinical staff and manager (use case) | patient, worklist, scores, gateway | Updated: beds (PAT-02), NEWS2, charge nurse, admin views, MON-03 |
| U04 | Pathway model (class) | `pathway_core.model`, `tokens`, `settings` | Updated: the settings module, `Retry.timeout_s`, override and emit |
| U05 | Condition language (class) | `pathway_core.conditions` | Matches |
| U06 | Packages | `packages/`, `services/` | Updated: care-events, service-metrics, scores, settings |
| U07 | Version lifecycle (state) | `designer.main` (`FROZEN`, `NEXT_STATUS`) | Updated: deploy states driven by deployer events |
| U08 | Save, verify, publish (sequence) | designer, verifier, web editor | Matches |
| U09 | Verification pipeline (activity) | `verifier.algorithm.verify` | Updated: settings checked (answer timeout, override, emit) |
| U10 | State-space exploration (activity) | `_Search.run/expand/analyse` | Matches |
| U11 | Data-flow fixed point (activity) | `verifier.dataflow` | Matches |
| U12 | Verifier (class) | `verifier` modules | Matches |
| U13 | One case across the services (sequence) | clinical Triage v4, all workers | Updated: the final clinical flow replaces the Sprint 3 example |
| U14 | Handle an event (activity) | `EngineService.on_event`, `_commit` | Updated: draining, timers table, snapshots every 50 events |
| U15 | Case lifecycle (state) | `Case` statuses | Updated: Compensating shown; "cancelled by staff" removed (not implemented) |
| U16 | Token lifecycle (state) | `Token`, `Case._failure`, `_timer` | Updated: retries, escalation, answer timeout |
| U17 | Task for a person (state) | `worklist.main` | Updated: report a problem (Failed), `claimed_at`, email/SMS alerts |
| U18 | Engine (class) | `engine.case`, `service`, `store` | Updated: Scheduler, timers, snapshots, compensation methods |
| U19 | Failure handling (activity) | `Case._failure`, `_compensate` | Updated: the answer timeout enters as a temporary failure (decision 0008) |
| U20 | Failure and compensation (sequence) | `test_eng08_…` scenario | Matches (Lab and Transport are test workers) |
| U21 | Deploy (sequence) | `deployer.main` (health every 0.2 s, 30 s) | Matches |
| U22 | Simulation loop (activity) | `simulator.des` | Matches |
| U23 | Staffing Advisor (activity) | `simulator.advisor` | Matches |
| U24 | Simulation job (sequence) | `simulator.main`, web polling every 0.8 s | Matches |
| U25 | Virtual patient (state) | `simulator.des` | Matches |
| U26 | ML training (activity) | `ml/training/train.py` | Matches |
| U27 | Prediction through the broker (sequence) | `ml.main`, Triage v4 | Updated: Triage v4, answer timeout when the ML service is down |
| U28–U30 | Clinical pathways (activity) | exported by `scripts/export_uml.py` | Regenerated from Triage v4, Assessment v1, Visit v1 |
| U31 | Services and events (component) | Compose file, services | Final (Sprint 7) |
| U32 | Containers on one host (deployment) | `docker-compose.yml` | Final (Sprint 7) |
| E1 | Tables per service (ER) | every `db.py` / `store.py` | Updated: all eight schemas (was Sprint 1 only) |

Found in the code while checking:
- The deployer's status comment listed `stopped`; the code uses `draining` and `retired`.
  The comment is fixed.

Not done: rendering. PlantUML is not installed on this machine, so the diagrams were checked
by reading, not by rendering. `scripts/render_uml.sh` renders them all (and fails on any
syntax error) once `plantuml.jar` is available.

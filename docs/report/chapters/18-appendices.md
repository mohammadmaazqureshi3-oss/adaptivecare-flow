# Appendix A — Backlog and traceability {.unnumbered}

The full product backlog, with each story's priority, points and sprint, the tests that carry its
ID, and the diagrams and decisions that name it. Generated from the repository by
`scripts/traceability.py`.

{{include docs/closure/traceability.md}}

# Appendix B — Event and API contract {.unnumbered}

The contract as kept in the repository (`contracts/events.md`). Changes to it required a recorded
design decision (`CLAUDE.md`, rule 1).

{{include contracts/events.md}}

# Appendix C — Design decisions {.unnumbered}

| No. | Decision | Phase |
|-----|----------|-------|
| 0001 | The Verifier stops a path at its first unsafe marking | Sprint 2 |
| 0002 | The gateway enforces roles; services trust its identity headers | Sprint 1 |
| 0003 | Routing keys, deterministic ids and reply correlation | Sprint 3 |
| 0004 | Timers, escalation, retries, compensation and the charge-nurse role | Sprint 4 |
| 0005 | Simulator modelling choices | Sprint 5 |
| 0006 | Clinical pathways, chaining, overrides and the urgency model | Sprint 6 |
| 0007 | Hardening: encryption, monitoring, alerts, a new task type | Sprint 7 |
| 0008 | An answer timeout for service and ML tasks | Closure |

The full texts are in `docs/decisions/`.

# Appendix D — Prompt-log excerpts {.unnumbered}

Two complete logs are reproduced: Sprint 3, where the engine's invariants were established, and
Closure. The others are in `docs/ai-log/`.

{{include docs/ai-log/sprint-3.md}}

{{include docs/ai-log/closure.md}}

# Appendix E — Model card {.unnumbered}

{{include docs/ml/model-card.md}}

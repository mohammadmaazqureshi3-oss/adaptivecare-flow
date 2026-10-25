# Prompt log — Sprint 5: Algorithm 3, the Pathway Simulator and Staffing Advisor

Sprint goal: a staffing recommendation with intervals; the Erlang C test passing.
Stories: DES-06, SIM-01, SIM-02, SIM-03, SIM-04, DEP-02. UML: U22–U25. Decision 0005. Tool: Claude Code.

## Produced
- `simulator/des.py`: discrete-event simulation with a future-event list, thinning for hourly
  arrival rates, priority queues per role, time-weighted statistics after warm-up; virtual
  cases moved by pathway-core's `TokenGraph` (the same token rules as Verifier and Engine).
- `stats.py`: replications, Student-t 95% intervals (SciPy), adaptive stopping, cap flag.
- `advisor.py`: greedy staffing search with common random numbers; `exhaustive` for checking.
- `queueing.py`: Erlang C, used only for validation.
- `scenario.py`: scenario, targets, readiness check (DES-06).
- Simulator service (background jobs, stored scenarios and results), gateway rules for
  designers and managers, Simulate page with intervals, utilisation bars and advice.
- DEP-02: engine `/drain`, deployer undeploy and drain watcher, Draining/Retired statuses,
  Undeploy button; the dev stack can now stop an engine.

## Where the AI was wrong and the tests caught it (for the report, Section 14 item 4)
1. **A test that proved nothing.** The first priority-queue test checked only that urgent
   patients were served at all, and simulated a hopelessly overloaded queue (10 s). Rewritten
   to compare mean waits by urgency in a busy but stable queue (utilisation 0.9).
2. **Urgency bookkeeping.** The first version recorded each case's urgency by wrapping a
   method after the fact, and lost cases that completed instantly. Replaced by recording
   the urgency at arrival.
3. **A wrong node count in a test** (19, not 20) for NFR-PERF-03: the test was fixed, the
   pathway now has 20 nodes as the NFR states.

## Measured results
- **SIM-04 Erlang C:** exact W_q = 21.33 min (λ = 8/h, mean service 12 min, c = 2); inside the
  simulated 95% interval in **92 of 100** experiments (pass mark 90).
- Little's law holds within the interval; no arrivals → no waits; 1 nurse at λ > capacity →
  mean wait grows with run length (1 d < 2 d < 4 d).
- **SIM-03:** greedy recommendation = exhaustive optimum (3 nurses, 4 doctors, cost 13): gap 0.
- **NFR-PERF-03:** 30 replications × 7 days × 20-node pathway in **5.0 s** (≤ 60 s).
- Triage at 6 patients/h, 2 nurses: utilisation 40% [40–41], mean wait 0.7 min [0.7–0.8],
  target "≤ 5% of urgency 1–2 wait > 5 min for confirmation" met at 1% [1–2].

## Tests
Simulator 28 (DES-06 readiness 5, simulation 7, statistics 3, validation 6, advisor 4,
service 4 — of which several parametrised), engine +1 (draining), deployer +2 (undeploy),
designer +1 (lifecycle forward only). Browser: Simulate with advice on Triage; undeploy of
the imaging engine through the dev stack (engine stopped, version Retired).

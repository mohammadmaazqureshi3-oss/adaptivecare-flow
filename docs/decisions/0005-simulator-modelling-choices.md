# 0005 — Simulator modelling choices

**Status:** accepted · **Sprint:** 5 · **Stories:** SIM-01..04, DES-06, DEP-02

## Context
Section 8 fixes the algorithm (discrete-event simulation, thinning, priority queues,
replications with 95% intervals, greedy advisor, validation against Erlang C and Little's
law) but leaves several modelling details open.

## Decisions
1. **Same token rules.** A virtual case is a pathway-core marking moved with `TokenGraph`.
   A task's move is split: the token is taken when the work starts and put on the next arrow
   when it ends. Fallback arrows are not simulated (tasks do not fail in the simulation).
2. **Decisions.** Conditions are evaluated when every name they read is sampled data
   (only `urgency` in Sprint 5); otherwise the branch probabilities decide, which must then
   exist on every branch and sum to 1 (checked before a run, DES-06).
3. **Queues.** One pool per human role; non-preemptive priority by (urgency, arrival).
   Service and ML tasks need no staff. Escalation is not simulated.
4. **Metrics** (after the warm-up): wait = request to start of service, per role (mean,
   95th percentile); utilisation and queue length time-weighted; deadline miss = request
   to completion longer than the task's deadline; a target is the share of patients (of the
   urgency levels named) whose wait for that task exceeds its limit; length of stay; time-
   average patients in system and arrival rate (Little's law).
5. **Stopping rule.** 10 replications, then 5 more at a time until every key metric's
   half-width is ≤ 5% of its mean *or* below a small absolute tolerance (0.25 min for waits,
   0.01 for utilisation, 0.005 for shares), at most 100; otherwise the cap is reported.
   Without the absolute tolerance, metrics near zero (an idle role's wait) never converge.
6. **Advisor.** 10 fixed replications per candidate with common random numbers (separate
   random streams for arrivals, work and routing, seeded per replication); shortfall =
   Σ max(0, upper − limit)/limit; when no single addition helps, add to the busiest role.
   The recommendation is re-run adaptively before it is shown.
7. **Urgency mix.** An illustrative default (1: 3%, 2: 17%, 3: 40%, 4: 30%, 5: 10%) until
   ML-01 (Sprint 6) measures the KTAS dataset; scenarios can set their own.
8. **Undeploy (DEP-02).** The deployer calls the engine's `POST /drain`; the engine stores
   the flag and ignores its start trigger; a watcher checks `running_cases` every 2 s and
   stops the engine at zero. Version: Deployed → Draining → Retired (only forward).

## Measured (for the report)
Erlang C coverage 92/100 (target ≥ 90); greedy vs exhaustive gap 0 on the two-role case;
NFR-PERF-03: 30 replications × 7 days × 20 nodes in 5.0 s (target ≤ 60 s).

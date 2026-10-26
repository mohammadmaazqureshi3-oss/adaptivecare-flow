# 0008 — An answer timeout for service and ML tasks

**Status:** accepted · **Phase:** Closure · **Requirement:** NFR-ROB-01 · supersedes 0007 item 8

## Context
Checking every NFR against the delivered system (Closure, Section 18) showed that
NFR-ROB-01 ("with the ML service down, triage continues through the fallback within 2
retries") was only met for a running ML service that answers with a failure. A stopped
service never answers: its request waits in the queue and the case waits with it. The
earlier test used "no model installed", which is a different situation; the planned demo
step "stop the ML container" would have failed.

## Decision
A service or ML task that has somewhere to go (a retry policy or a fallback) gets an answer
timeout: `retry.timeoutS`, default 30 s. When the engine requests the task it also schedules
a `timeout` timer for that attempt. If the timer fires while the token still waits on the same
attempt, the engine handles it exactly like a temporary `TaskFailed`: retry with backoff
while retries remain, then the fallback, then compensation. An answer that arrives later is
ignored, because the token has moved on (the same rule as any late reply, I1).

People's tasks keep deadlines and escalation instead. Tasks with no retry and no fallback
still wait for their service, since failing them would undo the case.

The timer uses the engine's existing timer table, so it survives restarts, and its due time
is derived from the request event, so replay stays deterministic (I3).

The clinical Triage (v4) sets 10 s for the model and the NEWS2 score, so a nurse gets the
manual task about half a minute after the service stops.

## Consequences
- An engine change in `case.py` (the timer kind and one scheduling call) and in
  pathway-core (`response_timeout`).
- The editor gains "No answer after (s)".
- New tests: settings validation, the engine's unanswered-attempt sequence, and a system
  test with no ML service at all.
- A service that is merely slow (longer than the timeout) now causes a retry; its late
  answer is ignored. That is safe, because tasks are duplicate-safe, but the timeout must
  exceed the service's normal p95 (11 ms for the model).

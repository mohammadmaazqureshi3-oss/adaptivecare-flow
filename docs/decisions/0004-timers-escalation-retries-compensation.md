# 0004 — Timers, escalation, retries, compensation and the charge-nurse role

**Status:** accepted · **Sprint:** 4 · **Stories:** ENG-06..09, DEP-01

## Context
Section 7 describes the failure order (retry, fallback, compensate) and timers that go
through `on_event`, but leaves some meanings open, and the plan's own triage example
escalates to `charge_nurse`, which is not a user role.

## Decisions
1. **Timers.** The case asks for a timer with an internal `TimerScheduled` event. The
   engine stores it in its `timers` table in the same transaction (not in the outbox). A
   scheduler loop (every second) turns due timers into `TimerFired` events whose id is
   derived from the timer and whose time is the due time, and passes them to `on_event`.
   Firing twice after a crash is therefore harmless (I1) and replay stays exact (I3). Due
   times are computed from the inbound event's time, never from the clock.
2. **Escalation meaning.** At the deadline the task moves to escalation level 1; each
   level's `afterMin` is how long that level has before the next one; after the last level
   the manager is alerted (`NotificationRequested`, role manager) and nothing more is
   scheduled. A reassignment reopens the task for the new role and resets its due time.
   The worklist ignores a reassignment whose level is not higher than the task's (late copies).
3. **Retry meaning.** `retry.max` counts retries after the first attempt (max 2 = at most
   3 attempts), with delays `baseDelayS × 2^(attempt−1)`. A retried request keeps its wait
   id, so a late success of an earlier attempt still completes the task, once.
4. **Compensation order.** Step x happened before y if x completed no later than the event
   that requested y. Undo levels follow reverse happened-before; one level's undos run in
   parallel; the next level starts when all of them report `Compensated`. With nothing to
   undo the case ends Failed; a failing undo ends it Failed and alerts the manager.
   Human undo actions become "Undo: …" worklist tasks.
5. **Snapshots** every 50 events per case (`snapshots` table); loading = snapshot + tail.
6. **Roles.** `charge_nurse` joins the user roles with a nurse's permissions, so escalated
   tasks have someone to see them. Permission matrix: as Nurse, plus escalations.
7. **Deployer runtimes.** Deploy logic depends on a `Runtime` (start, healthy, stop):
   Docker Engine API in Compose, in-process in the dev stack, a fake in tests. The deployer
   runs as root in Compose only because the Docker socket belongs to root (NFR-SEC-04
   still holds: no other service has the socket).

## Consequences
All time-based behaviour is deterministic and testable with a fake clock. The Docker
runtime and RabbitMQ bus are not yet exercised against real daemons (Docker unavailable);
the same logic runs in-process in tests and the dev stack.

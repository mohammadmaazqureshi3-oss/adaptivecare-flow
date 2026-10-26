# Sprint 4: Algorithm 2 reliability and Deploy

## Goal

*Kill the engine mid-case and watch it resume; deploy a version as its own engine.*

## Sprint backlog

| Story | Points | Summary |
|-------|-------:|---------|
| ENG-06 | 5 | An overdue task escalates along the chain the designer drew |
| ENG-07 | 5 | A failed task is retried with backoff, then follows the fallback branch if one is drawn |
| ENG-08 | 8 | Without a fallback, finished steps are undone in reverse order and the case ends Compensated |
| ENG-09 | 5 | After an engine crash every case resumes exactly where it was |
| DEP-01 | 8 | Deploying a published version starts its own engine container and queue |
| | **31** | |

## User stories and acceptance criteria

- **ENG-08** — *Given* a transfer that fails with no fallback after bed and lab steps finished,
  *then* the lab order is cancelled before the bed is released and the case ends Compensated.
- **ENG-09** — *Given* 50 running cases, *when* the engine is killed and restarted, *then* every case
  continues from the same state and no task is requested twice.
- **DEP-01** — *Given* a published version, *when* the admin deploys it, *then* a new engine is
  healthy within 30 seconds and `PathwayDeployed` is published.

## Design

### Time as events (decision 0004)

A case asks for a timer by emitting an internal `TimerScheduled` event. The engine stores it in its
`timers` table in the same transaction as the change, instead of the outbox. A scheduler loop runs
every second and turns due timers into `TimerFired` events, whose id is derived from the timer and
whose timestamp is the due time, and passes them to the same `on_event`. Firing a timer twice after a
crash is therefore harmless (I1), and replay stays exact (I3). Due times are computed from the
inbound event's time, never from the clock, so a test can run hours of deadlines in milliseconds
with a fake clock.

### Failure handling

The plan fixes the order: retry, then the drawn fallback, then compensation (diagram U19).

- **Retries (ENG-07).** A temporary failure is retried while retries remain, after
  `baseDelayS × 2^(attempt−1)` seconds. A retried request keeps its wait id, so a late success of an
  earlier attempt still completes the task, once.
- **Fallback.** A failure for good moves the token onto the fallback arrow the designer drew.
- **Compensation (ENG-08).** With no fallback, running branches are cancelled and finished steps
  that have an undo action are undone in reverse **happened-before** order. Step *x* happened before
  *y* if *x* completed no later than the event that requested *y*. Steps of one level are undone in
  parallel, and the next level starts when all of them report `Compensated`. With nothing to undo,
  the case ends Failed; a failing undo ends it Failed and alerts the manager. A person's undo action
  becomes an "Undo: …" task in the worklist.

In Closure, NFR-ROB-01 showed that a service which is *down* never answers, so none of this ran.
Automated tasks now also have an **answer timeout** that counts silence as a temporary failure
(decision 0008, chapter 16). The diagram below shows the final version.

{{uml U19}}

{{uml U20}}

### Deadlines and escalation (ENG-06)

At the deadline, a task moves to level 1 of the drawn chain (for example, from nurse to charge
nurse) and the role is notified; each level's `afterMin` is how long that level has before the
next; after the last level the manager is alerted and nothing more is scheduled. The worklist
ignores a reassignment whose level is not higher than the task's, because escalations can arrive
late or twice. Escalation needed someone to escalate *to*, so a `charge_nurse` role was added with a
nurse's permissions (decision 0004).

{{uml U17}}

### Recovery (ENG-09)

Every 50 events a case's state is saved as a snapshot; loading a case means the latest snapshot
plus the events after it. A test proves that snapshot plus tail equals a full replay.

### Deploy (DEP-01): model to engine

{{uml U21}}

The deployer depends on a `Runtime` interface with `start`, `healthy`, `stop` and `url`. There are
three implementations: the Docker Engine API in Compose, an in-process runtime in the development
stack, and a fake in tests. Deploying generates the engine configuration from the model (PIM →
PSM, chapter 5), creates the schema, starts the engine, polls `/health` every 0.2 s for up to 30 s,
records the deployment and publishes `PathwayDeployed`; the designer then marks the version
Deployed. An engine that is not healthy in time is stopped and the deployment marked failed. On
restart the deployer resumes the deployments it knows. The deployer is the only service with the
Docker socket (NFR-SEC-04).

## Implementation notes

`TaskReassigned` and `NotificationRequested` events; worklist reassignment and reopening; an
Alerts page; a Deploy button for admins; `CancelRequested` and `CompensateRequested` for workers;
the `snapshots` table.

## AI usage

1. **Undo order** (caught by the ENG-08 acceptance test). Bed and lab were undone together.
   Completing the bed and requesting the lab happen in the *same* event, so "completed before
   requested" must be ≤, not <. Fixed: the lab is now cancelled before the bed is released.
2. **Cancelling a task that had already failed** (caught by an existing test). Compensation sent
   `CancelRequested` to the failing task as well. The failed token is now retired first.
3. **Silent no-op edits** (caught in the running system). Two scripted replacements in
   `dev_stack.py` matched nothing, because the formatter had reflowed the lines; the deployer port
   went missing. Lesson recorded: scripted edits must fail loudly when they do not apply.

## Tests and results

- Escalation with a fake clock, including the boundary (9:59 not due, 10:00 due); no escalation when
  done in time; timers firing twice after a crash; retry timing (0.9 s / 1 s, 2.9 s / 3 s); a
  permanent failure skips retries; a late success of an earlier attempt counts once; compensation
  order and levels; a failing undo; replies ignored while compensating; snapshot plus tail equals a
  full replay.
- **ENG-09 acceptance: 50 cases killed and restarted, every task requested exactly once.**
- Deployer: configuration generation, deploy with health wait, idempotent deploy, unpublished
  version refused, unhealthy engine stopped, resume after restart.
- Gateway: NFR-SEC-03 — designers publish, only admins deploy.

Test functions at the tag: 169 Python.

## Review and retrospective

**Review** (browser): the deployer resumed the Triage engine after a restart; the admin deployed
the imaging pathway, its engine started and the version became Deployed. **Keep:** fake clocks;
an hour of escalations ran in a test in milliseconds. **Stop:** scripted edits without a check
that they applied. **Try:** the same `Runtime` abstraction for draining (Sprint 5).

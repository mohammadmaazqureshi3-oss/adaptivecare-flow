# Prompt log — Sprint 4: Algorithm 2 reliability, and Deploy

Sprint goal: kill the engine mid-case and watch it resume; deploy a version as its own engine.
Stories: ENG-06, ENG-07, ENG-08, ENG-09, DEP-01. UML: U17, U19–U21. Decision 0004. Tool: Claude Code.

## Produced
- **Timers** (`timers` table, `Scheduler`): deadlines, retry delays and timer nodes become
  `TimerFired` events through `on_event`, with ids derived from the timer and the due time
  as their timestamp.
- **ENG-06** escalation along the drawn chain (`TaskReassigned`, `NotificationRequested`),
  manager alert after the last level; worklist reassigns and reopens; Alerts page.
- **ENG-07** retries with exponential backoff for temporary failures, then the fallback.
- **ENG-08** compensation: running branches cancelled, finished steps with an undo action
  undone level by level in reverse happened-before order; human undos become worklist tasks.
- **ENG-09** snapshots every 50 events; load = snapshot + tail.
- **DEP-01** deployer: PIM → PSM (`engine_config`), schema creation, start, health wait
  ≤ 30 s, `PathwayDeployed`, resume after restart; designer marks versions Deployed;
  Deploy button for admins; dev stack uses the deployer with a local runtime.
- `charge_nurse` role (decision 0004).

## Where the AI was wrong and the tests caught it (for the report, Section 14 item 4)
1. **Undo order (caught by the ENG-08 acceptance test).** Bed and lab were undone together.
   Completing the bed and requesting the lab happen in the same event, so "completed before
   requested" must be ≤, not <. Fixed; the lab is now cancelled before the bed is released.
2. **Cancelling a task that had already failed (caught by an existing test).** Compensation
   sent `CancelRequested` to the failing task as well as to the other running one. The failed
   token is now retired first.
3. **Silent no-op edits to the dev stack (caught in the running system).** Two scripted
   replacements in `dev_stack.py` matched nothing because the formatter had reflowed the
   lines, so the deployer port was missing and the designer never got the bus (no
   Deployed status). Fixed with exact-match edits; the lesson for the AI log: scripted edits
   must fail loudly when they do not apply.

## Tests
- Engine policies (12): escalation chain with a fake clock (boundary at 9:59), no escalation
  when done in time, timers firing twice after a crash, retry backoff timing (0.9 s / 1 s,
  2.9 s / 3 s), permanent failure skips retries, late success of an earlier attempt,
  compensation order and levels, failing undo, ignoring replies while compensating,
  snapshot + tail = full replay, **50 cases killed and restarted with every task requested
  exactly once** (ENG-09 acceptance).
- Worklist (+6): reassignment, out-of-order escalations, alerts per role, cancellation,
  undo tasks answering Compensated. Deployer (6): PSM, deploy with health wait, idempotent
  deploy, unpublished refused, unhealthy engine stopped and marked failed, resume.
- Gateway: NFR-SEC-03 (designers publish, only admins deploy). System: escalation end to end.
- Browser: deployer resumed the Triage engine after a restart; admin deployed the imaging
  pathway, its engine started and the version became Deployed.

## Not yet verified
- `DockerRuntime` and `RabbitBus` against real daemons (Docker Desktop not running).

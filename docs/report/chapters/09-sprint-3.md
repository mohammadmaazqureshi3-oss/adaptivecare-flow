# Sprint 3: Algorithm 2 — the Execution Engine core

## Goal

*A patient flows through a pathway; duplicate messages are ignored.*

## Sprint backlog

| Story | Points | Summary |
|-------|-------:|---------|
| ENG-01 | 5 | Registering a patient starts a case on the deployed pathway whose trigger matches |
| ENG-02 | 8 | Each task is requested from the right service and its result moves the case on |
| ENG-03 | 5 | Decisions choose their branch from live case data, including the model's output |
| ENG-04 | 5 | Parallel branches run together and the join fires exactly once |
| ENG-05 | 5 | Duplicate and late messages never change a case twice |
| WRK-01 | 5 | Nurses and doctors see tasks for their role, claim them and complete them with the required outputs |
| | **33** | |

## User stories and acceptance criteria

- **ENG-04** — *Given* two branches that finish within the same millisecond, *when* both results
  arrive, *then* the join fires exactly once and the next task is requested once.
- **ENG-05** — *Given* every message delivered twice, *when* 100 cases run, *then* every case history
  equals the history of a run without duplicates.
- **WRK-01** — *Given* a task for nurses, *then* only nurses see it; it must be claimed before it is
  completed; completing it requires exactly the outputs the pathway declares, with the right types.

## Design

### What the engine must survive

The engine runs each real patient case through its deployed pathway, across services. It must
give one correct outcome per case even when messages are delivered twice (the broker delivers at
least once), arrive late or out of order, arrive at the same moment, when the engine crashes at
any point, when a task service fails briefly or for good, and when a person misses a deadline.
Five invariants make this precise; the tests must prove them:

- **I1** — each event changes a case at most once;
- **I2** — a parallel join fires exactly once for each set of arriving branches;
- **I3** — replaying a case's stored events rebuilds exactly the same state;
- **I4** — every case ends in exactly one final state;
- **I5** — no requested task is lost after a crash.

### A pure interpreter inside a transactional shell

The design splits the engine in two (diagram U18):

1. `Case.apply(event)` (`services/engine/engine/case.py`) is a **pure, deterministic** function: it
   moves the case's tokens with the token rules and returns the events to send. It reads no clock
   and does no I/O. Outbound ids are derived from the inbound event (uuid5 of the case id, the
   inbound id and the position), and outbound timestamps copy the inbound one. Replaying the
   stored inbound events therefore rebuilds the same state *and* the same outbound events, byte
   for byte (I3).
2. `EngineService.on_event(event)` (`service.py`) is the shell: lock, filter, load, apply, commit.

```python
def on_event(event):
    if draining and is_trigger(event): return              # DEP-02 (Sprint 5)
    case_id = uuid5(pathway, version, event.event_id) if is_trigger(event) else event.case_id
    with lock(case_id):                                    # one event per case at a time (I2)
        with transaction() as s:
            if s.exists(case_events, event_id=event.event_id):
                return                                     # duplicate (I1)
            case = cache.get(case_id) or load(s, case_id)  # snapshot + later events (I3)
            outbound = case.apply(event)                   # pure token rules
            s.add(case_events(event))
            s.add_all(timers(outbound) | outbox(outbound)) # in ONE transaction (I5)
            s.upsert(cases_summary(case))
    relay.notify()                                         # the outbox relay publishes afterwards
```

An exception before the commit rolls everything back and drops the cached case, so a half-applied
change cannot survive; the broker redelivers the message. Consumers acknowledge only after
committing.

{{uml U14}}

### Correlating replies (decision 0003)

A reply must reach the right engine and the right waiting token. Requests are routed as
`<Type>.<target>` and replies as `<Type>.<pathway>.v<version>`, so a reply can never reach another
version's engine. Within a case, each time a token starts waiting it gets a fresh **wait id**
(`t0.1@vitals#2`): token, node, and a counter. A request carries the wait id, and a reply is accepted
only by the token currently waiting on exactly that id. A late or duplicate reply for an earlier
wait finds no such token and is recorded but ignored.

{{uml U13}}

{{uml U15}}

{{uml U16}}

### The message layer

`packages/care-events` provides the envelope, deterministic ids and routing keys; a `Bus` interface
with two implementations — an **in-memory bus** with topic routing, redelivery and fault injection
(deliver twice, shuffle), and a **RabbitMQ bus** for Compose; the **transactional outbox** (rows
written in the same transaction as the change, published afterwards by a relay thread) and the
**inbox** (handled event ids, so a consumer can drop duplicates).

No broker was available on the development machine (Docker was not running), and the plan's risk
response R4 was to build and test the engine in one process first. So every test and the
development stack run on the in-memory bus; the RabbitMQ adapter has been written but not run
against a live broker (chapter 16).

## Implementation notes

- **worklist** (WRK-01) consumes `TaskRequested.worklist`, creates a task for the drawn role, and on
  completion validates the outputs against the declared types and sends `TaskCompleted` through its
  outbox. A failed or finished case cancels its open tasks.
- **patient** publishes `PatientRegistered` through its outbox, in the same transaction as the
  registration — without the patient's name or birth date.
- **ml** was a placeholder that failed permanently, so Triage took its manual fallback until
  Sprint 6.
- **web**: a Tasks page for nurses and doctors.
- `scripts/dev_stack.py` runs every service in one process on the in-memory bus, for machines
  without Docker.

## AI usage

The prompt was "continue" (Sprint 3 in the plan). The tests caught four problems:

1. **Reply correlation** (found by the 1,000-case replay test). Replies were first matched by token
   id, but a token keeps its id as it moves on. A duplicate `TaskFailed` for the ML task arrived
   after the token was already waiting at Manual triage, and was taken as Manual triage failing,
   which failed the case. The fix is the wait id described above.
2. **A default trigger** (found in the running dev stack). A Start without a trigger was treated as
   `PatientRegistered`, so the imaging example would have started a case for every patient. Now no
   trigger means no automatic start.
3. **History order** (found in the browser). Each inbound event was recorded after the events it
   caused.
4. **Shared bus lifecycle.** In the dev stack all services share one bus, and a service stopping it
   on shutdown would stop everyone's. Services now start and stop only a bus they created.

## Tests and results

The special tests for this algorithm (plan Section 14):

- **Duplicates (I1, ENG-05 acceptance)**: every message delivered twice for 100 cases; every history
  equals a clean run's.
- **Reordering**: shuffled and duplicated delivery together.
- **Concurrency (I2)**: two join inputs sent from two threads at the same moment, 30 runs; the join
  fires once every time.
- **Crashes (I5)**: the engine stopped after the commit but before publishing, and after receiving
  but before committing; nothing is lost and nothing is done twice.
- **Replay (I3)**: 1,000 random cases rebuilt from their stored events reach the same state.
- Interpreter unit tests: routing on live data, join once, fallback, wrong outputs rejected, late
  messages, deterministic ids.
- System test: patient → engine → ml → worklist with every message delivered twice.

Test functions at the tag: 142 Python.

## Review and retrospective

**Review** (browser): a nurse registers P000004 → "Manual triage" and "Measure vital signs" appear →
SpO₂ 86 routes the case to "Confirm urgent level" → the case completes, the join fired once.
**Keep:** a pure interpreter with all I/O outside; it made replay and fault injection simple to
test. **Stop:** correlating by long-lived identifiers. **Try:** time-based behaviour (deadlines,
retries) as events through the same `on_event`, not as threads (Sprint 4).

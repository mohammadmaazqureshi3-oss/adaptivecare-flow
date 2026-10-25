# Prompt log — Sprint 3: Algorithm 2, the Execution Engine core

Sprint goal: a patient flows through a pathway; duplicate messages are ignored.
Stories: ENG-01..05, WRK-01. UML: U13–U16, U18. Decision 0003. Tool: Claude Code.

## Approach (risk R4 in the plan)
No broker was available (Docker not running, RabbitMQ not installed), and the plan says to
build and test the Engine in one process first. So every service talks through a `Bus`
interface: `InMemoryBus` (with fault injection) carries the tests and the local dev stack;
`RabbitBus` is written for Compose but **has not yet run against a live broker**.

## Produced
- `packages/care-events`: envelope with deterministic ids and routing keys, `InMemoryBus`
  (topic routing, redelivery, dead letters, deliver-twice and shuffle faults), `RabbitBus`,
  transactional outbox with relay, inbox duplicate filter.
- `engine/case.py`: the pure token interpreter (start, tasks, decisions on live data,
  parallel split and join, end, fallback on permanent failure). `engine/service.py`:
  `on_event` with per-case lock, duplicate filter, replay-based loading, one transaction.
- worklist (WRK-01), `PatientRegistered` from the patient service via its outbox, an ml
  placeholder that fails permanently until Sprint 6 (so Triage takes its manual fallback),
  Tasks page, `scripts/dev_stack.py` (one process, engines started per published version).

## Where the AI was wrong and the tests caught it (for the report, Section 14 item 4)
1. **Reply correlation (found by the 1,000-case replay test).** Replies were matched by token
   id, but a token keeps its id as it moves on. A duplicate `TaskFailed` for the ML task
   arrived after the token was waiting at Manual triage and was taken as Manual triage
   failing, failing the case. Fix: each wait gets its own id (`t0.0@predict#1`) and a reply
   must name it (decision 0003). Regression test added.
2. **Default trigger (found while running the dev stack).** A Start without a trigger was
   treated as `PatientRegistered`, so the imaging example would have started a case for
   every new patient. Fix: no trigger means no automatic start. Regression test added.
3. **History order (found in the browser).** Each inbound event was recorded after the
   events it caused. Fixed; test added.
4. **Shared bus lifecycle.** In the dev stack all apps share one bus; an app stopping it on
   shutdown would have stopped everyone's. Apps now start and stop only a bus they created.

## Tests
- Interpreter: 12 unit tests on Triage (routing on live data, join once, fallback, wrong
  outputs, late messages, deterministic ids, history order).
- Reliability (plan Section 7): every message twice for 100 cases equals a clean run
  (ENG-05 acceptance); shuffled + duplicated delivery; two join inputs from two threads,
  30 runs (I2); crash after commit before publish and crash before commit (I5); 1,000 random
  cases replayed to the same state (I3); restart rebuilds from the store.
- care-events 18, worklist 10, patient +1 (event carries no name), system test 2
  (patient → engine → ml → worklist with every message delivered twice).
- Browser: nurse registers P000004 → Manual triage and vital signs appear → SpO₂ 86 routes
  to "Confirm urgent level" → case completed, join fired once.

## Still to do for Sprint 3's plan
- Run the system flow on RabbitMQ in Docker Compose (integration test), when Docker is up.

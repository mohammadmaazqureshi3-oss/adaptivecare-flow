# 0003 — Routing keys, deterministic ids and reply correlation

**Status:** accepted · **Sprint:** 3 · **Stories:** ENG-01..05, WRK-01 · **Invariants:** I1, I2, I3

## Context
Section 9 of the plan names the events and says each engine has its own queue
(`engine.triage.v3`), but not how a reply finds the engine that asked, how duplicates
are recognised, or how a reply is matched to the right task.

## Decision
1. **Routing keys** on the topic exchange `care.events`:
   - requests: `<Type>.<target service>`, e.g. `TaskRequested.worklist`, `TaskRequested.PredictUrgency`;
   - replies: `<Type>.<pathway>.v<version>`, e.g. `TaskCompleted.triage.v1`; an engine binds
     `*.<pathway>.v<version>` and receives only its own replies;
   - broadcasts: the type alone, e.g. `PatientRegistered`, `CaseCompleted`.
   The envelope gains one field, `target`, to build request keys.
2. **Deterministic ids.** Every event a service derives from another gets
   `uuid5(namespace, parts)`: engine output = (case id, inbound event id, position);
   a reply = (request id, type, position); a case id = (pathway, version, trigger event id).
   Processing the same input twice yields the same ids, so consumers drop copies by id (I1).
3. **Correlation by wait id.** A token keeps its id as it moves, so a reply could be taken
   for a later task of the same token (found by the replay test). Each wait gets its own id
   `token@node#n`; requests carry it in `token_id` and `payload.task_id`, and a reply is
   accepted only by the token currently waiting on exactly that id.
4. **Timestamps of outbound events** are the inbound event's timestamp, so replay (I3)
   reproduces events byte for byte.
5. A Start without a `trigger` is not started by any event (no default trigger).

## Consequences
Replies never reach the wrong engine version, duplicates and late replies are harmless,
and the engine's state is a pure function of its stored inbound events. Old engines keep
their queues while they drain (Sprint 4).

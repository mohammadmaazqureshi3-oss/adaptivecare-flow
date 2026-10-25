# Event contract

Changing this file needs a recorded design decision (CLAUDE.md rule 1).

All run-time services talk through one RabbitMQ topic exchange, `care.events`.
Each consumer has its own queue; each engine has one named after its version,
such as `engine.triage.v3`. Consumers acknowledge a message only after committing
their change, so delivery is at least once and duplicates are filtered by `event_id`.

## Envelope

| Field       | Type            | Meaning                                         |
|-------------|-----------------|-------------------------------------------------|
| `event_id`  | UUID            | Unique; used for duplicate filtering (I1)       |
| `type`      | string          | One of the types below; also the routing key    |
| `case_id`   | UUID or null    | The case the event belongs to                   |
| `token_id`  | string or null  | The token (pathway position) it answers         |
| `pathway`   | string          | Pathway id, e.g. `triage`                       |
| `version`   | int             | Pathway version                                 |
| `attempt`   | int             | Delivery attempt, for retries with backoff      |
| `timestamp` | ISO 8601 (UTC)  | When the producer created it                    |
| `payload`   | object          | Type-specific, below                            |

## Catalog

| Event                                                     | Producer              | Consumers                     | Payload                        |
|-----------------------------------------------------------|-----------------------|-------------------------------|--------------------------------|
| `PatientRegistered`                                       | patient               | engines whose trigger matches | Patient id, arrival data       |
| `TaskRequested.<service>`                                 | engine                | ml, patient, worklist         | Task id, inputs, deadline      |
| `TaskCompleted`                                           | ml, patient, worklist | engine                        | Outputs                        |
| `TaskFailed`                                              | ml, patient, worklist | engine                        | Reason; temporary or permanent |
| `TaskReassigned`                                          | engine                | worklist                      | New role, new deadline         |
| `NotificationRequested`                                   | engine                | worklist                      | Recipient role, message        |
| `CompensateRequested.<service>`                           | engine                | patient, worklist             | Step to undo                   |
| `Compensated`                                             | patient, worklist     | engine                        | Step undone                    |
| `CancelRequested.<service>`                               | engine                | ml, patient, worklist         | Task id                        |
| `CaseStarted`, `CaseCompleted`, `CaseCompensated`, `CaseFailed` | engine          | worklist                      | Case summary                   |
| `PathwayDeployed`, `PathwayRetired`                       | deployer              | designer                      | Pathway, version, container    |

## REST: verifier (Sprint 2)

`POST /verify` with a pathway JSON body → `{status: SAFE|UNSAFE|TOO_LARGE, errors: [...],
states_explored, search_complete, elapsed_ms}`. Each error has `type`, `property`,
`nodes`, `message`, `path` (list of `{node, consumed, produced}` moves), and for
condition errors `edge` and `pos`.

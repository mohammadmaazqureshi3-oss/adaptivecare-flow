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
| `target`    | string or null  | Requests only: the service a request is for     |
| `payload`   | object          | Type-specific, below                            |

## Routing keys and ids (decision 0003)

| Kind       | Routing key                         | Example                    | Bound by                  |
|------------|-------------------------------------|----------------------------|---------------------------|
| Request    | `<Type>.<target>`                   | `TaskRequested.worklist`   | the target service        |
| Reply      | `<Type>.<pathway>.v<version>`       | `TaskCompleted.triage.v1`  | that engine: `*.triage.v1`|
| Broadcast  | `<Type>`                            | `PatientRegistered`        | engines whose trigger matches, worklist |

Derived events have deterministic ids (uuid5), so a duplicate input produces duplicate ids
and consumers drop the copy. A task request's `token_id` is its *wait id* (`t0.1@vitals#2`);
a reply must carry the same value, and only the token waiting on exactly that id accepts it.

### `TaskRequested` payload
`task_id` (= wait id), `node`, `label`, `kind` (human/service/ml), `role`, `service`,
`inputs` {name: value}, `outputs` [{name, type}] the reply must contain, `deadline`, `patient_id`.

### `TaskCompleted` / `TaskFailed` payload
`{outputs: {...}, completed_by}` · `{reason, temporary: bool}`

### `PatientRegistered` payload
`patient_id` (record number), `age`, `sex`, `arrival_mode`, `chief_complaint`: no name or birth date.

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

## REST: auth, gateway and designer (Sprint 1, decision 0002)

All user requests go through the gateway, which checks the token and the role
(`services/gateway/gateway/permissions.py`) and adds `X-User-Id`, `X-User-Email`, `X-User-Role`.

| Endpoint | Body → result |
|----------|---------------|
| `POST /auth/login` | `{email, password}` → `{access_token, refresh_token, token_type, user}` |
| `POST /auth/refresh` | `{refresh_token}` → `{access_token, token_type}` |
| `GET /auth/me` | → `user` |
| `GET/POST /users`, `PATCH /users/{id}` | admin only; users are deactivated, never deleted |
| `GET/POST /pathways`, `GET/PATCH /pathways/{id}` | `{id, name}`; a new pathway starts as draft v1 (Start → End) |
| `GET/POST /pathways/{id}/versions` | POST starts the next draft from the latest published version |
| `GET/PUT /versions/{id}` | PUT `{model}` saves a draft; 409 on a published version |
| `POST /versions/{id}/verify` | runs the verifier; status becomes `verified` only if SAFE |
| `POST /versions/{id}/publish` | needs status `verified`; the version becomes immutable |
| `POST /conditions/check` | `{condition, variables}` → `{ok, errors: [{kind, message, pos}]}` |
| `GET /patients?q=`, `POST /patients`, `GET /patients/{id}` | nurse, doctor (PAT-01) |
| `GET /tasks`, `POST /tasks/{id}/claim`, `/release`, `/complete` | nurse, doctor; tasks of the caller's role (WRK-01) |

Engine (internal, per version): `GET /cases`, `GET /cases/{id}` (state and full history).

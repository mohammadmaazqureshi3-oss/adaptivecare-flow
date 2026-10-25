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

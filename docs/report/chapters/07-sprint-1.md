# Sprint 1: pathway model, editor, condition language and login

## Goal

*Draw, save and version a pathway; role checks work.*

## Sprint backlog

| Story | Points | Summary |
|-------|-------:|---------|
| AUTH-01 | 3 | An admin creates users and gives each a role |
| AUTH-02 | 3 | A user logs in and receives a token that expires |
| AUTH-03 | 5 | The system refuses any action the user's role does not allow |
| DES-01 | 8 | A designer draws a pathway with start, end, tasks, decisions, merges, parallel splits and joins, and timers |
| DES-02 | 3 | A designer declares variables and each task's inputs and outputs |
| DES-03 | 5 | A designer writes branch conditions and sees syntax errors while typing |
| DES-05 | 3 | Every Publish creates an immutable version |
| | **30** | |

## User stories and acceptance criteria

- **AUTH-02** — *Given* a valid login, *then* an access token valid for 15 minutes and a refresh token
  valid for 8 hours are issued; *given* an expired, forged or refresh-type token on an API call,
  *then* the gateway answers 401 (NFR-SEC-01).
- **AUTH-03** — *Given* any route and any role, *then* the gateway forwards the request if and only if
  the permission matrix allows it; unknown routes are refused (NFR-SEC-02).
- **DES-03** — *Given* `urgency <= 2 or spo2 <` in a branch, *then* the editor marks the position of the
  syntax error as the designer types; *given* `urgency == "high"` with `urgency: int`, *then* a type
  error names both types.
- **DES-05** — *Given* a published version, *then* saving or publishing it again is refused (409), and
  a change needs a new draft copied from it.

## Design

### The pathway language

A pathway is a directed graph saved as JSON (Table 7.2), whose meaning is fixed by eight token
rules taken from Petri nets. A **token** sits on an arrow, and a **marking** — how many tokens sit on
each arrow — is the state of a case.

| Element | Meaning | Designer's settings |
|---------|---------|---------------------|
| Start | Where every case begins | Trigger event, input variables |
| Task | Work by a person, a service or the model | Kind, role or service, inputs, outputs, deadline and escalation, retries and answer timeout, fallback, undo action, override check, duration |
| Decision (XOR split) | Exactly one outgoing branch | A condition per branch plus a default; probabilities for the simulator |
| Merge (XOR join) | Passes on each arriving token | — |
| Parallel split (AND split) | Starts every outgoing branch | — |
| Parallel join (AND join) | Waits for every incoming branch | — |
| Timer | Waits a fixed time | Minutes |
| End | Where a case finishes | Optionally an event to announce |

: Table 7.2 — Elements of the pathway language.

The eight rules:

1. **Start** puts one token on its outgoing arrow.
2. **Task** takes the token from its incoming arrow and, when the work completes, puts one on its
   outgoing arrow.
3. **Decision** takes the token and puts one on exactly one outgoing arrow: the first branch whose
   condition holds, otherwise the default.
4. **Merge** takes a token from any incoming arrow and puts one on its outgoing arrow.
5. **Parallel split** takes one token and puts one on every outgoing arrow.
6. **Parallel join** fires only when every incoming arrow holds a token; it takes one from each and
   puts one on its outgoing arrow.
7. **Timer** holds the token for its duration, then passes it on.
8. **End** takes the token; a case is complete when an End has fired and no token is left.

The verifier applies every allowed move (a decision may take any branch); the engine applies the
real move for a real patient (decisions evaluate on live data); the simulator applies sampled
moves for virtual patients.

{{uml U04}}

### The condition language

Designers write conditions such as `spo2 < 90 or news2 >= 7 or urgency <= 2`. The grammar is
implemented by a lexer and a recursive-descent parser with one function per rule:

```
expr     := and_expr { "or" and_expr }
and_expr := not_expr { "and" not_expr }
not_expr := "not" not_expr | cmp
cmp      := value [ ("<" | "<=" | ">" | ">=" | "==" | "!=") value ]
          | value "in" "[" literal { "," literal } "]"
value    := NUMBER | STRING | "true" | "false" | IDENT | "(" expr ")"
```

The parser builds a tree (`Literal`, `Name`, `BoolOp`, `Not`, `Compare`, `InList`). The type checker
requires every name to be a declared variable, comparisons to have compatible types, and `and`,
`or`, `not` to take booleans. The engine and the simulator evaluate the same tree. Every error
carries its character position, which the editor uses to draw a caret under it.

{{uml U05}}

### Versions and roles

A version moves Draft → Verified → Published, and later Deployed → Draining → Retired (diagram U07,
chapter 8). Any edit returns a Verified version to Draft, so "Verified" always refers to exactly
the saved model. The gateway holds the permission matrix and forwards the identity to services
(decision 0002).

{{uml U08}}

## Implementation notes

- **auth**: bcrypt hashes; access and refresh JWTs; `/auth/login`, `/auth/refresh`, `/auth/me`,
  `/users` for admins; the first admin comes from the environment. Users are deactivated, never
  deleted, to keep the audit trail; an admin cannot demote or deactivate themself.
- **gateway**: a tuple of `Rule(method, path, service, roles)` compiled to regular expressions;
  a proxy that adds `X-User-Id`, `X-User-Email` and `X-User-Role`.
- **designer**: pathways and versions; `POST /versions/{id}/verify` calls the verifier and stores
  the report; Publish requires a SAFE report of the exact version; `/conditions/check` runs
  pathway-core's parser and type checker for the editor's live checks.
- **web**: React Flow canvas with a palette, an inspector for every setting, a variables panel, live
  condition errors with a caret, and a report panel that highlights the error nodes and path.

## AI usage

The prompt was "start Sprint 1: the React Flow pathway editor and the auth service with JWT and
roles". Four problems were caught, three of them outside the unit tests:

1. **Nodes invisible on the canvas** (found in the browser). The editor loaded the model a second
   time after React Flow had measured the nodes; the new node objects had no measurements and
   stayed hidden. The cause was a callback whose identity changed on every render.
2. **A branch could not be clicked**: with right-angle arrows, two branches ran along the same line.
   Curved arrows and a wider click area fixed it, a usability issue for NFR-USE-01.
3. **Edges without ids** in hand-written JSON crashed the editor; a round-trip unit test caught it.
4. **FastAPI could not resolve dependencies** declared inside `create_app` while
   `from __future__ import annotations` was on; every endpoint returned 422 until the first auth
   test exposed it. The routes later moved to module-level routers, which also kept every function
   under the complexity limit.

## Tests and results

Auth 11 tests (expired, forged and wrong-kind tokens); gateway: every rule × every role (85 cases at
the time) plus spot checks from the permission matrix; designer 11 (with the real verifier
in-process); web 7 (model round trip, layout, helpers). Test functions at the tag: 77 Python and 7
web.

## Review and retrospective

**Review** (in the browser): log in as the designer, open the deadlock example, press Verify →
UNSAFE with the path highlighted; replace the join with a merge by drawing; Verify → SAFE
(8 states); Publish → the version becomes read-only. **Keep:** checking the running system, not
only the tests; the browser found what unit tests could not. **Stop:** relying on rendering details
in tests. **Try:** step-by-step replay of counterexamples, because a highlighted path alone did not
explain *why* the case was stuck (carried into Sprint 2).

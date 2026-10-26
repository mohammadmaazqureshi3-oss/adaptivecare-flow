# Part II — Sprint cycles {.unnumbered}

# Sprint 0: setup and architecture baseline

## Goal

*All empty services start with one command, and the shared semantics exist before any feature
uses them.*

## Sprint backlog

Repository layout; ten service skeletons with `/health`; the gateway's `/health/all`; Docker
Compose with PostgreSQL (one schema per service) and RabbitMQ; the CI workflow; the rules file for
AI tools (`CLAUDE.md`); the prompt log; the first UML drafts (U01–U03, U06, U31, U32). Beyond the
plan, the `pathway-core` library and the core of Algorithm 1 were built in this sprint, because
every later algorithm depends on the token rules. The professor's approval was still pending, and
the daily note of that day records it as the blocker for Sprint 1 (requirement P14).

## User stories and acceptance criteria

Sprint 0 has no user stories; its "acceptance" is technical. Every service answers `/health`;
`docker compose up` starts everything; CI runs lint, types, tests and security scans. The
`pathway-core` library has one test per token rule (test-first, as the XP practice in the slides
asks) and partition and boundary tests on the condition language.

## Design

The repository is a monorepo: `packages/` for shared libraries, `services/<name>/<name>/` for each
service with `services/<name>/tests/`, `contracts/` for the event and API contract, `pathways/`
for models, and `docs/` for UML, decisions, prompt logs and daily notes. The development view is
diagram U06 (chapter 5).

The central design decision of the whole project was taken here: **the token rules exist once**.
`pathway_core.tokens.TokenGraph` turns a pathway into a set of arrows and offers
`initial_marking()`, `enabled_moves(m)`, `fire(m, move)` and `replay(path)`. A marking is a tuple of
token counts, one per arrow. The verifier explores every move, the simulator samples moves, and
the engine makes real moves, all through the same class.

## Implementation notes

- `pathway_core.model` loads a pathway from JSON into frozen dataclasses (`Pathway`, `Variable`,
  `Node`, `Edge`) and validates references. A task's `fallback` is stored on the node and turned
  into an extra arrow marked `fallback=True`, so the token rules treat it like any branch.
- `pathway_core.conditions` has a hand-written lexer, a recursive-descent parser with one method
  per grammar rule (`expr`, `and_expr`, `not_expr`, `cmp`, `value`, `literal`), a type checker and
  an evaluator over the same tree (chapter 7).
- The verifier's first version (chapter 8) was written against this library.
- `docker-compose.yml` uses a YAML anchor for the common service settings; only the gateway's port
  and the web app's port are published to the host.

## AI usage

The prompt was "read the project proposal and start creating the project". The assistant
produced the layout, the skeletons, Compose, the CI workflow, the rules file and the UML drafts.
Three mistakes in the verifier were caught in this sprint by the tests (chapter 8): exploration did
not stop at unsafe markings, so a loop around a broken parallel block grew without bound; the
"too large" status hid real errors; and one token-rule test fired a decision twice because the test
forgot that Start's token already sat on the arrow. The last one was the test's fault, not the
rule's.

## Tests and results

77 tests passed at the end of the sprint (the daily note of 25 October), 53 of them test
functions with the remainder parametrised: one per token rule, the condition language's
partition and boundary tests, and the verifier's 12-pathway catalogue and property-based tests.
The Compose start test could not be run, because Docker was not running on the machine; this
blocker carried through the whole project (chapter 16).

## Review and retrospective

**Review:** the verifier rejected the imaging deadlock example and accepted the fixed version, from
the command line. **Keep:** building the shared library first. **Stop:** nothing yet. **Try:** a
decision record (`docs/decisions/`) for every choice the plan leaves open, starting with how the
verifier treats unsafe markings (decision 0001).

# Prompt log — Sprint 0 (and early Sprint 2 work)

For each story: goal, prompt summary, what the AI produced, what was kept, changed or
rejected and why, tests added. Tool: Claude Code.

## Sprint 0 skeleton

- **Goal:** repository, CI, Compose skeleton, pathway-core skeleton, rules file, prompt log.
- **Prompt summary:** "Read the project proposal and start creating the project."
- **Produced:** folder layout, nine service skeletons with `/health`, gateway `/health/all`,
  `docker-compose.yml`, PostgreSQL schema script, GitHub Actions CI, `CLAUDE.md`, UML drafts.
- **Kept / changed:** _to fill in after your review._
- **Tests:** verifier `/health`; Compose start test to run once Docker is up.

## pathway-core: model, token rules, condition language (DES-02, DES-03 groundwork)

- **Produced:** `model.py` (JSON ↔ model; a task's `fallback` becomes an extra arrow),
  `tokens.py` (the eight token rules), lexer, recursive-descent parser, type checker, evaluator.
- **Tests:** one test per token rule, partition and boundary tests on the triage condition.

## Algorithm 1 — Verifier (VER-01..06)

- **Produced:** structural checks, BFS over markings, co-reachability for livelocks,
  data-flow fixed point, condition checks, shortest counterexamples.
- **Where the AI was wrong and the tests caught it (keep for the report, Section 14 item 4):**
  1. The first version kept exploring past unsafe markings. Hypothesis generated a loop
     around a parallel block whose join was changed to a merge. Tokens then grew without
     bound and the search stopped at the 200,000-state limit (TOO_LARGE) instead of reporting
     duplicate work. Fix: a path stops at its first unsafe marking, which counts as
     "settled" for the livelock check.
  2. With nested loops, even safe markings went past the limit after duplicate work had
     already been found. Design decision: a counterexample proves UNSAFE whether or not the
     search finished. TOO_LARGE now means the limit was reached *before* any error was found,
     and `search_complete` is reported separately.
  3. A token-rule test fired the decision twice because it forgot that Start's token
     already sits on the arrow into the decision. The test was wrong, not the rule.
- **Tests:** 12-pathway catalog, property-based tests (block-structured ⇒ SAFE; flipping one
  join is detected; every counterexample replays), NFR-PERF-01 timed test.

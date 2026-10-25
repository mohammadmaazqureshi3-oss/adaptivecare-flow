# Prompt log — Sprint 2: Algorithm 1, the Verifier

Sprint goal: the imaging deadlock is found, highlighted and replayable on the canvas.
Stories: VER-01..06 (algorithm built early, in Sprint 0), DES-04, PAT-01, plus NFR-USE-01.
UML: U07–U12. Tool: Claude Code.

## NFR-USE-01 — step-by-step counterexample replay
- **Prompt summary:** "Start Sprint 2: step-by-step counterexample replay, DES-04 tests and patient registration (PAT-01)."
- **Produced:** `replay(model, path)` in `web/src/editor/model.ts`, a pure function that rebuilds
  the marking after each move with the token rules; controls ⏮ ◀ ▶ ▶ ⏭ and a slider in the report
  panel; tokens drawn as ● on arrows, the firing node outlined in blue, earlier moves in amber, the
  stuck nodes in red only at the final step. Opens on the bad state; hidden while there are
  unsaved edits, because the report belongs to the saved version.
- **Kept / changed:** fallback arrows in the editor now use pathway-core's id (`task~>target`),
  so a counterexample through a fallback can be drawn. Before, the editor used its own id.
- **Found in the browser:** the decision diamond's highlight was invisible, because the shape is
  clipped with `clip-path`, which hides borders. Fix: stronger fill colours for that shape.
- **Tests:** replay of the Verifier's real deadlock path; ids match the canvas, fallback included.
  Measured: Verify answers in under 1 ms on the server for the imaging example (target 2 s).

## DES-04 — task settings
- **Produced:** `pathway_core/settings.py` validates deadlines, escalation levels, retries,
  undo actions, durations, timers and who does a task, and gives the Engine and Simulator typed
  values (`Deadline`, `Retry.delay(attempt)`, `Duration`). The Verifier reports each problem
  as a `settings` error, so a draft can be saved half-finished but not published.
  The editor hides retries on human tasks.
- **Where testing caught problems (keep for the report, Section 14 item 4):**
  1. The new rule "a human task needs a role" made the property-based generator's tasks
     invalid; Hypothesis reported every generated pathway UNSAFE. The generator was fixed,
     not the rule.
  2. The report kept one error per type and node, so two different problems on one node
     (for example a decision with one branch *and* no default) showed as one. The message
     is now part of the key.
- **Tests:** 34 pathway-core partition and boundary tests, 4 verifier tests, 1 designer test.

## PAT-01 — register and search patients
- **Produced:** patient service (record number P000001…, name, date of birth, sex, arrival
  mode, chief complaint), search by record number or part of the name (wildcards escaped),
  newest arrivals first; a possible duplicate (same name and birth date) needs an explicit
  confirmation; gateway rules for nurses and doctors; Patients page in the web app.
- **Found by tests:** SQLite returns stored times without a time zone, so `arrived_at`
  differed between the create response and a later read. Stored times are now always
  returned as UTC (the designer had the same issue).
- **Deferred on purpose:** encryption of name and birth date (NFR-SEC-05) is planned for
  Sprint 7 and changes only `patient/db.py` and the search; `PatientRegistered` events come
  with the outbox in Sprint 3 (ENG-01).
- **Tests:** 18 patient tests, 2 new gateway spot checks.

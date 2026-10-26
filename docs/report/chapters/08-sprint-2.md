# Sprint 2: Algorithm 1 — the Pathway Verifier

## Goal

*The imaging deadlock is found, highlighted and replayable on the canvas.*

## Sprint backlog

| Story | Points | Summary |
|-------|-------:|---------|
| VER-01 | 8 | Publish is blocked when the pathway can deadlock; the stuck path is highlighted |
| VER-02 | 5 | Duplicate work, unfinished cases and loops with no exit are reported |
| VER-03 | 2 | Steps no patient can reach are reported |
| VER-04 | 5 | A step that reads data that may be unset is reported |
| VER-05 | 3 | Condition type errors are reported before Publish |
| VER-06 | 2 | "Too large to verify" with statistics when the state limit is reached |
| DES-04 | 5 | Deadlines, escalation chains, retries, fallback branches and undo actions on tasks |
| PAT-01 | 3 | A nurse registers and searches patients |
| | **33** | plus NFR-USE-01 (counterexample replay) |

The verifier's core had been built early, in Sprint 0; this sprint completed it, connected it to
the editor and added the replay.

## User stories and acceptance criteria

- **VER-01** — *Given* a decision that feeds a parallel join, *when* I press Verify, *then* the result
  is UNSAFE, the deadlock is listed and its path is highlighted; *given* the corrected pathway, the
  result is SAFE and Publish is enabled.
- **VER-04** — *Given* a step that reads lab results set on only one branch, *when* I press Verify,
  *then* a missing-data error names the step and the variable.
- **NFR-USE-01** — errors appear on the canvas within 2 s, and the counterexample can be replayed step
  by step.

## Design

### What "sound" means

The verifier decides, before any patient is affected, whether a pathway is sound, and if not,
returns each error with the shortest sequence of moves that causes it. The definition is van der
Aalst's soundness [1, 2] applied to the control flow, plus two data checks:

1. **Option to complete** — from every reachable marking, a completed marking can still be reached.
2. **Proper completion** — when End fires, no other token remains.
3. **No dead steps** — every node fires in at least one reachable marking.
4. **Safeness** — no arrow ever holds more than one token.
5. **Data soundness** — every variable a step reads is set on every path that reaches it, and
   every condition type-checks.

| Error | Property | What it means for a patient |
|-------|:--------:|-----------------------------|
| Deadlock | 1 | The case is stuck: no move is possible and it is not finished |
| Cannot finish (livelock) | 1 | The case can loop forever with no way out |
| Unfinished case | 2 | The pathway ends while work is still running |
| Dead step | 3 | A step no patient can ever reach |
| Duplicate work | 4 | A step runs twice for the same patient |
| Missing data | 5 | A step reads a value that may not exist yet |
| Type error | 5 | A condition compares incompatible values |
| Settings | — | A task's deadline, retry, undo, … is malformed (DES-04) |

: Table 8.1 — Errors the verifier reports.

### The algorithm

{{uml U09}}

The pipeline (diagram U09) runs structural checks first: references, exactly one Start and at
least one End, the shape of each node (a join has several inputs and one output, a decision has a
default), and a breadth-first search from Start plus a reverse one from the Ends. If the structure
is broken, the search cannot run and only those errors are reported.

The heart is the exploration of every reachable marking (diagram U10, `_Search` in
`services/verifier/verifier/algorithm.py`):

```python
def verify(p, limit=200_000):
    report = Report()
    if not structural_checks(p, report):           # fatal structure errors stop here
        g = TokenGraph(p)
        explore(g, report, limit)                  # properties 1-4 (below)
        if not report.errors and not report.too_large:
            report.extend(dataflow_check(p))       # property 5: needs sound control flow
        check_conditions(p, report)                # property 5: parse and type-check
    check_settings(p, report)                      # DES-04
    return report.deduplicate()

def explore(g, report, limit):
    m0 = g.initial_marking()
    parent, queue, succ = {m0: None}, deque([m0]), {}
    while queue:
        m = queue.popleft()                        # breadth-first: shortest paths first
        if max(m) > 1:
            unsafe.add(m); continue                # decision 0001: do not expand
        moves = g.successors(m)                    # token rules; a decision: one move per branch
        succ[m] = [m2 for _, m2 in moves]
        if not moves and not g.is_complete(m):
            report.deadlock(m, path_to(m, parent))
        for move, m2 in moves:
            fired.add(move.node)
            check_move(m, move, m2)                # duplicate work, unfinished case
            if m2 not in parent:
                if len(parent) >= limit: return report.too_large()
                parent[m2] = (m, move); queue.append(m2)
    can_finish = backward_reachable(succ, completed | unsafe)
    can_deadlock = backward_reachable(succ, deadlocks)
    for m in seen - can_finish - can_deadlock:     # point of no return only
        if parent[m] is None or parent[m][0] in can_finish:
            report.cannot_finish(m, path_to(m, parent))
    if not unsafe:                                 # a cut path could hide reachable steps
        report.dead_steps(all_nodes - fired)
```

{{uml U10}}

Markings are tuples, so `m2 not in parent` is a constant-time lookup. Because the search is
breadth-first, the first path found to any bad marking is a shortest one, which keeps
counterexamples short and readable. The `parent` map gives that path back by walking from the
marking to the start.

The **livelock check** is a co-reachability analysis. The search records each marking's
successors; a backward search from the completed markings finds every marking that can still
finish. A marking outside that set, and outside the set that can only reach deadlocks (already
reported), is a livelock. Only the *point of no return* is reported: the first marking on the
path that cannot finish while its predecessor still could.

### Two design decisions (decision 0001)

Property-based testing exposed a flaw in the plan's version of the algorithm. In a loop around a
parallel block whose join had been turned into a merge, every round added a token, so markings
grew without bound and the search stopped at the 200,000-state limit with TOO_LARGE, hiding a
simple duplicate-work error. Two rules fix it:

1. A path stops at its first **unsafe** marking (an arrow with two tokens): property 4 is already
   broken there. Such markings count as settled for the livelock check, so they never cause a
   false "cannot finish", and dead steps are not reported when any path was cut, since they might
   be reachable beyond the cut.
2. **Status**: UNSAFE whenever an error was found, even if the limit was reached; TOO_LARGE only
   when the limit was reached before any error. A separate flag says whether the search finished.

### Data flow

{{uml U11}}

The data-flow check (diagram U11, `services/verifier/verifier/dataflow.py`) computes, for every
node, the set of variables certainly set when a case arrives there. It starts from "every
variable" at every node (the top of the lattice) and iterates in reverse post-order until nothing
changes. At a parallel join the incoming sets are united, because every branch ran; elsewhere
they are intersected, because only one path is guaranteed. A node writes its outputs, and Start
writes its input variables. A fallback arrow carries the failed task's *input* set, because a task
that failed set none of its outputs. Every name a node reads that is not in its set is reported
as missing data. The loop ends because sets only shrink and there are finitely many variables;
it costs at most nodes × arrows × variables steps. The union at a join is valid only when the
control flow is sound, which is why the check runs only after the exploration found no error.

### Complexity and limits

Time grows with the number of reachable markings times the number of nodes; memory with the
number of markings. Markings grow exponentially with parallel branches: *k* branches of *n* steps
can create up to (*n*+1)<sup>*k*</sup> markings. A 30-node pathway with four branches of seven
steps has at most 8<sup>4</sup> = 4,096. The limit of 200,000 states guarantees that the search
always ends. Real clinical pathways stay small: the final Triage has 16 reachable markings,
Assessment 11 and Visit 5.

{{uml U12}}

### Worked example

The imaging example (`pathways/imaging_deadlock.json`) has a decision "Imaging type" choosing
X-ray *or* CT, followed by a parallel join "Wait for both". The verifier explores 6 markings in
0.1 ms and reports:

> **Deadlock**: the case is stuck at wait_both and is not finished — path: register → imaging_type
> → xray.
> **Dead step**: no patient can reach wait_both. **Dead step**: no patient can reach end.

Replacing the join with a merge (`imaging_fixed.json`) makes the pathway SAFE after 8 markings.

### Counterexample replay (NFR-USE-01)

A highlighted path says *where* a case gets stuck but not *why*. The editor's `replay(model, path)`
(`web/src/editor/model.ts`) rebuilds the marking after each move with the same token rules, and the
report panel steps through it: tokens are drawn as dots on the arrows, the node firing is outlined,
earlier moves are shown in amber, and the stuck nodes turn red at the final step. The replay opens
on the bad state. It is hidden while there are unsaved edits, because the report belongs to the
saved version.

### Task settings (DES-04)

`pathway_core/settings.py` validates and types each task's policies — who does it, deadline and
escalation chain, retries, undo action, duration distribution, timer minutes — and gives the engine
and simulator typed values (`Deadline`, `Retry.delay(attempt)`, `Duration`). The verifier reports
each problem as a *settings* error, so a draft can be saved half-finished but not published.

### Patients (PAT-01)

The patient service registers patients with a record number (`P000001`), searches by record
number or name, and asks for an explicit confirmation when the same name and birth date exist.

## AI usage

The prompt was "start Sprint 2: step-by-step counterexample replay, DES-04 tests and patient
registration". The cases where testing caught the AI's work:

1. The new rule "a human task needs a role" made the property-based generator's tasks invalid, and
   Hypothesis reported every generated pathway UNSAFE. The generator was wrong, not the rule.
2. The report kept one error per type and node, so two different problems on one node showed as
   one. The message is now part of the key.
3. SQLite returns stored times without a time zone, so `arrived_at` differed between the create
   response and a later read. All stored times are now returned as UTC.
4. The decision diamond's highlight was invisible in the browser, because the shape is clipped
   with `clip-path`, which hides borders.

## Tests and results

The special tests for this algorithm (plan Section 14):

- **A catalogue of 12 pathways with known answers**: one per error type plus sound ones.
- **Property-based (Hypothesis)**: random block-structured pathways, with every split closed by a
  join of the same type, must be SAFE; changing one join's type must be detected; every reported
  counterexample, replayed with the token rules, must reach the reported marking.
- **NFR-PERF-01**: a 30-node pathway with four parallel branches verifies in 0.04 s (target 2 s).
- The replay test in the web app reproduces the verifier's real deadlock path.

Test functions at the tag: 103 Python and 9 web; 34 new partition and boundary tests on the
settings alone.

## Review and retrospective

**Review:** in the browser, Verify on the imaging example lights up the deadlock; ▶ steps through
Register → Imaging type (X-ray) → X-ray → stuck at "Wait for both". **Keep:** property-based tests —
they found the unbounded-loop flaw that 12 hand-written cases missed. **Stop:** letting generated
test data drift from the model's rules. **Try:** a written decision for every behaviour the plan
leaves open; three were recorded in this sprint.

# 0001 — The Verifier stops a path at its first unsafe marking

**Status:** accepted · **Sprint:** 2 · **Stories:** VER-02, VER-06

## Context
Section 6 of the plan explores every reachable marking. When a pathway is unsafe inside
a loop (for example, a parallel split closed by a merge), tokens grow without bound, so the
search only ends at the 200,000-state limit and reports TOO_LARGE instead of the real error.

## Decision
1. A marking with any arrow holding more than one token is recorded (duplicate work) and
   not expanded. For the livelock check it counts as settled, so it never causes a
   false "cannot finish" report.
2. Dead steps are not reported when any path was cut. They could be reachable beyond the cut.
3. Status is UNSAFE whenever at least one error was found, even if the limit was reached.
   TOO_LARGE means the limit was reached with no error found. `search_complete` says whether
   the search finished.

## Consequences
Unsafe pathways are reported in milliseconds with a shortest counterexample. The report
may list fewer secondary errors for a pathway that is already unsafe. That is acceptable:
the designer fixes the first error and verifies again.

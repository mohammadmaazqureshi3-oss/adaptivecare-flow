# Presentation and demo rehearsal (plan Section 16)

The talk answers the professor's question "how does your system decide?": three decisions in the
order they happen (design, planning, run time), then a live demo that proves them.
Rehearse it three times with a timer, and record the demo once as the backup video (risk R11).

## The 15 minutes

| Time | Part | Content | Material |
|------|------|---------|----------|
| 0:00–1:00 | Problem | Pathways change often; hard-coded software lags. Goal: draw, verify, simulate, deploy, run | Report §1.1 |
| 1:00–2:30 | Solution | Design → Verify → Simulate → Deploy → Run; the four-category table; the architecture (U31) | Table 1.1, Table 4.4, U31 |
| 2:30–4:30 | Algorithm 1 | Soundness (5 properties); the imaging deadlock found in 6 markings; BFS ⇒ shortest counterexample; state explosion and the 200,000 limit; decision 0001 | U10, chapter 8 |
| 4:30–6:30 | Algorithm 3 | Simulation loop; staffing with intervals; Erlang C 92/100; greedy vs exhaustive gap 0; comparison of 2 vs 4 nurses | U22, U23, Table 11.1 |
| 6:30–8:30 | Algorithm 2 | One case across services (U13); invariants I1–I5 and the test that proves each; wait-id correlation; outbox; replay; the answer timeout found in Closure | U13, U14, chapter 9 |
| 8:30–12:00 | Live demo | The script below | |
| 12:00–14:00 | Process and quality | Scrum phases; velocity; 652 tests, 92.8% coverage; the AI rules file and the 33 defects found (Table 14.1) — be open that the increments took two days | Figures 3.1, 15.1; chapter 14 |
| 14:00–15:00 | Results and limits | Figure 13.2; limits: Docker path unrun, synthetic data, alpha test, calendar; next steps | Chapter 16 |

## Before the demo (checklist)

- [ ] Fresh state: move `.dev/*.db` aside, start the stack, run `scripts/seed_demo.py`.
- [ ] In the browser: four tabs, logged in as designer, admin, nurse and manager (demo accounts in
      `scripts/seed_demo.py`).
- [ ] Simulations computed beforehand (Triage v4, 6 patients/h, 2 and then 4 nurses), so the comparison
      opens instantly.
- [ ] One patient half-way through Triage (vital signs entered, confirmation open) for the restart step.
- [ ] The backup video is on the laptop, outside the browser.
- [ ] Docker variant only: `docker compose up --build` has run once on this laptop before the day.

## Demo script (3.5 minutes)

Two variants: with Docker Compose (the plan's), or with the development stack (`scripts/dev.sh`),
which is what has been tested on this machine.

1. **Verify (40 s).** As designer, open "Imaging (has a deadlock)". Press Verify → UNSAFE; press ▶ to
   replay: Register → Imaging type (X-ray) → X-ray → stuck at "Wait for both". Change the join to a
   merge, Verify → SAFE.
2. **Simulate (40 s).** Open Triage → Simulate → earlier runs → tick both → Compare: 4 nurses better
   on 8 of 14 figures, utilisation 40% → 20%, every figure with its interval.
3. **Deploy (30 s).** As admin, Pathways → the fixed imaging pathway → Publish (designer) → Deploy
   (admin) → Monitoring → Services shows the engine's metrics; in Compose, `docker ps` shows the new
   `engine-imaging_fixed-v…` container.
4. **Run (50 s).** As nurse, register a patient (ambulance, chest pain); take "Measure vital signs",
   enter SpO₂ 86, oxygen yes; the next task "Confirm urgency (urgent)" shows NEWS2 13 (high) and the
   model's level with its reasons; change the level → a reason is required; confirm. As manager,
   Monitoring → Cases → the case's timeline and the Assessment case that started.
5. **ML down (30 s).**
   - Compose: `docker compose stop ml`, register another patient.
   - Dev stack: stop it (Ctrl-C) and restart with `DEV_WITHOUT=ml ./scripts/dev.sh`, register another
     patient.
   Enter the vital signs; three prediction attempts go unanswered (10 s each, with 1 s and 2 s
   backoff); about 35 s later "Manual triage (model unavailable)" appears.
6. **Crash and resume (20 s).**
   - Compose: `docker kill` the triage engine container, then `docker start` it.
   - Dev stack: the restart in step 5 already did it. The patient prepared before the demo still has
     the confirmation task, and completing it finishes the case: nothing was lost (I3, I5).

If anything fails: switch to the backup video at the same step and continue talking.

## Questions he is likely to ask

| Question | Answer (with where to point) |
|----------|------------------------------|
| Isn't the Verifier just a BFS? | BFS is only the search order. The algorithm is the token semantics, five soundness properties, co-reachability for livelocks, the data-flow fixed point, and shortest counterexample reconstruction (`verifier/algorithm.py`, U10, U11). |
| What is its complexity? | Reachable markings × nodes; markings grow exponentially with parallel branches ((n+1)^k), so the 200,000-state limit guarantees termination; the clinical pathways have 5–16 markings. |
| Why stop at unsafe markings? | Inside a loop, unsafe markings grow tokens without bound, and the search would end in TOO_LARGE, hiding a simple error. Property-based tests found this (decision 0001). |
| What if two branch results arrive together? | A per-case lock processes them one at a time; the join checks all inputs and fires once; a two-thread test runs it 30 times (I2). |
| What if the engine crashes after saving but before sending? | The outbox rows are in the same transaction; the relay sends them after restart; consumers drop duplicates by event id (I5, I1). |
| How do you know replay gives the same state? | `Case.apply` is pure: no clock, no I/O, ids derived from the input. A test replays 1,000 random cases (I3). |
| What happens when the ML service is down? | Since Closure: no answer within 10 s counts as a temporary failure; two retries, then the manual-triage fallback (decision 0008). Before that, a stopped service made the case wait — found in Closure by checking the NFR's own situation. |
| Why simulate instead of using a formula? | Parallel steps, priorities, non-exponential durations and hourly arrivals have no closed formula; the formula is used where exact, to validate (Erlang C 92/100). |
| How many replications, and why? | Until every key metric's 95% half-width is ≤ 5% of its mean (or below a small absolute tolerance), between 10 and 100. |
| Is the Advisor optimal? | No, it is greedy; on the two-role case it matched exhaustive search (gap 0). |
| Is the ML model your Category 3? | No, Category 2. Category 3 is what the pathway does with its output, executed by the engine. |
| Why is the model's accuracy so low? | It is trained on synthetic data; the pipeline is real. The decision rule favours urgent recall (0.90) over accuracy, because under-triage harms patients. |
| How did you check AI-generated code? | Specification first (the plan), tests first, the full static gate, review in the running system; Table 14.1 lists 33 defects and how each was found. |
| Did the sprints really take two weeks each? | No. The increments were built in two days with an AI assistant; the report says so (chapter 3) and that no burndown exists. |
| Why microservices and not a monolith? | Pathways deployed as their own services, as required; fault isolation (the ML service can fail while triage continues); independent deployment. Costs handled with case ids and duplicate-safe consumers. |
| How do you change a pathway while patients are in it? | Versions are immutable; running cases finish on their version's engine, which drains then retires. Migration (MIG-01) is future work. |
| How is patient data protected? | Name and birth date encrypted (Fernet, key from the environment); search by a keyed blind index; events and alerts carry the record number only. |
| What would you do next? | Run the Docker path; train on the KTAS file; the alpha test; MIG-01 with a verifier-checked state mapping; mutual TLS. |

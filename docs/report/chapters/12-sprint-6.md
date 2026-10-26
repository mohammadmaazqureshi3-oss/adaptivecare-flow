# Sprint 6: the urgency model and the three clinical pathways

## Goal

*A full triage demonstration with the model; stop the model and watch the fallback.*

## Sprint backlog

| Story | Points | Summary |
|-------|-------:|---------|
| ML-01 | 8 | Train and evaluate the urgency model and record its metrics |
| ML-02 | 5 | The ml service answers PredictUrgency with level, probabilities, reasons and model version |
| WRK-02 | 3 | A nurse can override the model's suggestion only with a reason, which is logged |
| PAT-02 | 3 | Beds can be reserved and released, with an undo action |
| CLN-01 | 5 | The Triage pathway is drawn, verified, simulated, deployed and run end to end |
| CLN-02 | 3 | The Assessment pathway (parallel labs and imaging, then doctor review) works the same way |
| CLN-03 | 3 | The Visit pathway (bed reservation, transfer, undo on failure) works the same way |
| | **30** | |

## User stories and acceptance criteria

- **ML-02** — *Given* the vital signs and complaint, *then* the service answers within 100 ms (p95) with
  the outputs the pathway declared (level, confidence, a note with the top three reasons). *Given*
  no model, it answers a permanent failure so the pathway's fallback runs.
- **WRK-02** — *Given* a suggested level of 2, *when* the nurse confirms level 1 without a reason,
  *then* the completion is refused; with a reason it is accepted and logged.
- **CLN-03** — *Given* a failed transfer after a bed was reserved, *then* the bed is released and the
  Visit case ends Compensated.

## Design

### Data (ML-01)

The plan named the KTAS study dataset [6]. It was not available on the machine, so the documented
fallback of risk R6 was used: a synthetic generator (6,000 records, seed 7) with physiology by level
and 10% ambiguous labels. A loader for the study's file format (semicolons, decimal commas,
`KTAS_expert` as the label) is ready and tested on a fixture. Placing the file at
`data/ktas/data.csv` retrains the model on real data without code changes. The model's version name
(`urgency-v1-synthetic`), its model card and the service's `/health` all say "synthetic", so the
figures below prove the pipeline, not clinical accuracy (NFR-EXT-01).

### Training pipeline

{{uml U26}}

Seventeen features: age, sex, arrival by ambulance or referral, consciousness (AVPU), pain, systolic
pressure, pulse, respiration rate, temperature, SpO₂, and six complaint keywords (chest, breathing,
abdomen, fever, trauma, neurological). After cleaning impossible values and a stratified 80/20
split, three models are compared by 5-fold cross-validation on the training set: logistic
regression (the baseline), random forest and gradient boosting. All use balanced class weights,
because levels 1–2 are rare. Selection uses half urgent recall plus half macro-F1; the winner is
calibrated (sigmoid, 5-fold), explained with SHAP, and saved with its metrics.

| Model | Recall on levels 1–2 | Macro F1 | Selection score |
|-------|---------------------:|---------:|----------------:|
| Logistic regression | 0.858 | 0.665 | **0.762** |
| Random forest | 0.816 | 0.684 | 0.750 |
| Gradient boosting | 0.783 | 0.670 | 0.726 |

: Table 12.1 — Cross-validation on the training set.

### The decision rule

Calibration undid the class weights: with the usual "most likely level" rule, the calibrated model
rarely chose the rare urgent levels, and test recall on levels 1–2 fell to **0.696**. The model now
keeps its calibrated probabilities but decides "urgent" when P(1) + P(2) ≥ τ, with τ tuned on
out-of-fold training predictions for urgent recall ≥ 90%. That gives τ = 0.23 and a test urgent
recall of **0.899**. Over-triage rises, which is the safe direction, and a nurse confirms every
level anyway (decision 0006).

| Held-out test set | Value |
|-------------------|------:|
| Recall on levels 1–2 | 0.899 |
| Under-triage rate | 0.088 |
| Over-triage rate | 0.284 |
| Macro F1 | 0.472 |
| Brier score | 0.092 |

: Table 12.2 — Test results (synthetic data).

### Serving (ML-02)

{{uml U27}}

The ml service answers `TaskRequested.PredictUrgency` with the declared outputs (`urgency`,
`confidence`, `triage_note` with the top three reasons) plus all probabilities, the reasons and the
model version. Reasons are SHAP values of the uncalibrated model; yes/no features read as their
names ("chest complaint"). Without a model file it answers a permanent failure (the pathway's
fallback runs); a prediction error is temporary, so the engine retries. It is stateless: a reply's
id derives from its request's.

### Pathway chaining and overrides

An End can **announce an event** (`emit`), whose payload is the case data plus `from_case`.
Another pathway uses it as its trigger: Triage → `TriageCompleted` → Assessment →
`AdmissionRequested` → Visit → `PatientAdmitted`. The **override check** (WRK-02) is a task
setting `{suggested: urgency, decided: confirmed_urgency}`. The worklist refuses a completion whose
decision differs from the suggestion without a reason of at least five characters, and logs every
change. A person can also **report a problem** on a task, which fails it for good, so the pathway
takes its fallback or compensates.

### The three pathways

**Triage** became sequential. The plan's example predicted urgency in parallel with measuring the
vital signs, but the model needs the vital signs. Triage v2 measures, then predicts, then applies
a safety decision: `spo2 < 90 or sbp < 80 or urgency <= 2 or confidence < 0.7` routes to an urgent
confirmation with a 5-minute deadline. Both confirmations carry the override check (Sprint 7 added
NEWS2 and made it v3, Closure added answer timeouts and made it v4).

{{uml U28}}

**Assessment** starts on `TriageCompleted`, runs blood tests (nurse) and imaging (doctor) in
parallel, joins, and has a doctor decide on admission. It ends by announcing `AdmissionRequested`,
or discharges the patient.

{{uml U29}}

**Visit** starts on `AdmissionRequested`, reserves a bed through the patient service's `BedService`
(with the undo action `ReleaseBed` and retries while no bed is free), prepares the handover, and
transfers the patient within 60 minutes. A failed transfer releases the bed and compensates the
case.

{{uml U30}}

All three verify SAFE (16, 11 and 5 reachable markings) and are ready to simulate. The demo seed
installs each one through the platform itself: create or copy a draft, save, verify, publish,
deploy, and undeploy older running versions.

## AI usage

1. **Calibration undid the class weights** — found by reading the model card's confusion matrix,
   not by a failing test; fixed with the tuned threshold above.
2. **NaN is truthy** — the KTAS loader's `int(value or 0)` crashed on missing fields; caught by the
   fixture test in the study's format.
3. **The UML exporter** duplicated steps after a parallel join, then stopped too early at a merge
   that only rejoins a fallback; caught by reading its output, and a test now checks that every task
   appears exactly once.
4. **A plan inconsistency**, not a code bug: predicting before measuring (above).

## Tests and results

- Model: features, consciousness levels, loader fixture, synthetic generator, pipeline metrics,
  threshold, explanations, the shipped model loads; **NFR-PERF-04: prediction p95 11 ms** (≤ 100 ms).
- WRK-02 overrides, PAT-02 beds (idempotent reservation, release on undo, occupied on admission).
- **Clinical system tests**: Triage, Assessment, Visit, the ml, patient and worklist services and
  an in-memory bus that delivers every message twice — a patient from registration to an occupied
  bed with an override; a failed transfer releases the bed and compensates the visit; a discharge
  starts no visit.

Test functions at the tag: 226 Python.

## Review and retrospective

**Review** (browser): a nurse registers a patient and enters vital signs (SpO₂ 86); the model
suggests level 2 ("chest complaint; breathing rate 28; arrived by ambulance"); the safety rule routes
to the urgent confirmation; changing the level to 1 is refused without a reason and accepted with
one; Triage completes and the Assessment case starts. **Keep:** model cards; the decision rule
problem was visible only there. **Stop:** trusting cross-validated scores without looking at the
held-out confusion matrix. **Try:** a clinical score as a plug-in service, to prove that the engine
needs no change for new task types (CLN-04).

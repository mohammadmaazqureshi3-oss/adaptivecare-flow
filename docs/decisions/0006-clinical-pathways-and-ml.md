# 0006 — Clinical pathways, chaining, overrides and the urgency model

**Status:** accepted · **Sprint:** 6 · **Stories:** ML-01, ML-02, WRK-02, PAT-02, CLN-01..03

## Context
The plan's Triage example (Section 5) runs the prediction in parallel with the vital
signs, but the model's inputs (Section 11) include the vital signs. The plan also has three
pathways that must follow one another, and a rule that a nurse may override the model only
with a logged reason. The KTAS file was not available (risk R6).

## Decisions
1. **Triage v2 is sequential:** vital signs → prediction → safety decision → confirmation.
   The prediction cannot run before its inputs exist. Triage v1 (the parallel example)
   stays in `pathways/triage.json`; the clinical v2 is installed as a new version, verified,
   published and deployed, and v1 is undeployed (drained), the platform's own workflow.
2. **Chaining by events:** an End node may announce an event (`emit`). Its payload is the
   case data plus `from_case`; another pathway uses it as its start trigger:
   Triage → `TriageCompleted` → Assessment → `AdmissionRequested` → Visit → `PatientAdmitted`.
3. **Override check (WRK-02)** is a task setting `{suggested: <input>, decided: <output>}`.
   The worklist refuses a completion whose decision differs from the suggestion unless a
   reason (≥ 5 characters) is given, and logs it in `overrides` (readable by managers and
   admins). Both Triage confirmations carry it.
4. **Report a problem:** a person can fail a claimed task with a reason; for normal tasks
   the engine gets a permanent `TaskFailed` (fallback or compensation), for undo tasks
   `Compensated {ok: false}` (case Failed, manager alerted).
5. **Beds (PAT-02):** the patient service is the `BedService` worker; reservation is
   idempotent per request; no free bed is a temporary failure (retries with backoff);
   `ReleaseBed` undoes; `PatientAdmitted` marks the bed occupied.
6. **Urgency model:** synthetic data as the documented fallback (labelled in the version
   name `urgency-v1-synthetic`, the model card and `/health`). The KTAS loader is ready; a
   file at `data/ktas/data.csv` retrains on real data without code changes.
7. **Decision rule:** sigmoid calibration undoes the class weights, so "most likely level"
   misses urgent patients (urgent recall 0.696). The model keeps calibrated probabilities but
   decides "urgent" when P(1) + P(2) ≥ τ, with τ tuned on out-of-fold training predictions for
   urgent recall ≥ 90% (τ = 0.23; test urgent recall 0.899). Over-triage rises (safe direction;
   a nurse confirms every level).
8. **Reasons** are SHAP values of the uncalibrated model (the calibrated wrapper is not
   explainable directly); yes/no features read as their names ("chest complaint").

## Consequences
The three pathways run end to end with real services; the model's quality figures prove the
pipeline only, until the KTAS file is used.

# Prompt log — Sprint 6: ML and the three clinical pathways

Sprint goal: full triage demo with the model; stop the ML service and watch the fallback.
Stories: ML-01, ML-02, WRK-02, PAT-02, CLN-01, CLN-02, CLN-03. UML: U26–U30. Decision 0006.

## Produced
- **ML-01** `services/ml/training/`: KTAS loader, documented synthetic fallback, the six
  steps of Section 11 (clean, stratified split, 3 models × 5-fold CV, class weights,
  calibration + SHAP, versioned file), model card and metrics (`docs/ml/`).
- **ML-02** `ml/model.py`, `ml/main.py`: prediction with level, probabilities, confidence,
  top-3 reasons and version; only the declared outputs are sent; no model → permanent
  failure (fallback), prediction error → temporary (retry).
- **WRK-02** override check setting; worklist refuses an unexplained change and logs explained
  ones (`/overrides`); "report a problem" fails a task; editor inspector fields.
- **PAT-02** beds: `BedService` worker (reserve, release on undo, occupy on admission),
  REST and a Beds panel.
- **CLN-01..03** `pathways/clinical/`: Triage v2, Assessment, Visit, chained by events their
  End nodes announce (new `emit` setting). All three verify SAFE and are ready to simulate.
- `scripts/export_uml.py`: pathway JSON → PlantUML activity diagram (U28–U30).

## Where the AI was wrong and testing caught it (for the report, Section 14 item 4)
1. **Calibration undid the class weights.** Cross-validated urgent recall was 0.858, but the
   calibrated model's test recall was 0.696: "most likely level" rarely picks the rare urgent
   levels. Fixed with a threshold on P(1)+P(2) tuned out-of-fold (test recall 0.899).
   Found by reading the model card's confusion matrix, not by a failing test.
2. **NaN is truthy.** The KTAS loader wrote `int(value or 0)`; for `??` fields `value` is NaN,
   which is truthy, so `int(NaN)` crashed. Caught by the fixture test in the study's format.
3. **The UML exporter duplicated steps** after a parallel join (each branch carried on through
   the join), then stopped too early at a merge that only rejoins a fallback. Caught by
   reading the output; a test now checks each task appears exactly once.
4. **Plan inconsistency, not a code bug:** the Triage example predicts in parallel with the
   vital signs it needs. Resolved by Triage v2 (decision 0006).

## Measured
- Urgency model (synthetic): selected logistic regression; test urgent recall **0.899**,
  under-triage 8.8%, over-triage 28.4%, macro F1 0.47, Brier 0.092 (see the model card).
- **NFR-PERF-04:** prediction p95 **11 ms** (≤ 100 ms).
- Browser: nurse registered P000005, entered vital signs (SpO₂ 86); the model suggested level 2
  ("chest complaint; breathing rate 28; arrived by ambulance"); the safety rule routed to the
  urgent confirmation; an override to level 1 was refused without a reason and accepted with
  one; Triage completed and the Assessment case started (Blood tests task appeared).

## Tests
ML 17, worklist +3, patient +3, settings +5, exporter 5, clinical end-to-end 3 (admission to
an occupied bed; failed transfer releases the bed and compensates; discharge starts no visit).

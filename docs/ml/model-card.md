# Model card: urgency-v1-synthetic

Urgency level 1 (most urgent) to 5, KTAS scale. Decision support only, not a medical device:
a nurse always confirms or overrides the level, and safety rules in the pathway (oxygen below 90,
systolic pressure below 80, confidence below 0.7) send the patient to review whatever the model says.

> **Trained on synthetic data** (the documented fallback, risk R6). These numbers show the pipeline works; they say nothing about clinical accuracy. Put the KTAS study file at `data/ktas/data.csv` and run the training again to replace them.

- Data: synthetic-v1 (6000 records, seed 7) · train 4800 / test 1200 · levels {1: 210, 2: 928, 3: 2318, 4: 1881, 5: 663}
- Selected model: **logistic_regression** (sigmoid-calibrated, class-weighted)
- Decision rule: urgent (level 1 or 2) when P(1) + P(2) ≥ **0.23**, tuned
  on out-of-fold training predictions for urgent recall ≥ 90%;
  otherwise the likeliest of 3–5. With a plain "most likely level" rule the test urgent
  recall would be 0.696 (calibration undoes the class
  weights, so the rare urgent levels are rarely the most likely).
- Features: age, male, arrival_ambulance, arrival_referral, mental, pain, sbp, hr, rr, temp, spo2, kw_chest, kw_breath, kw_abdomen, kw_fever, kw_trauma, kw_neuro

## Cross-validation (5-fold, training set)

| Model | Recall on levels 1–2 | Macro F1 | Selection score |
|---|---|---|---|
| logistic_regression | 0.858 | 0.665 | 0.762 |
| random_forest | 0.816 | 0.684 | 0.750 |
| gradient_boosting | 0.783 | 0.670 | 0.726 |

## Held-out test set

| Metric | Value |
|---|---|
| Recall on levels 1–2 | **0.899** |
| Macro F1 | 0.472 |
| Under-triage rate (predicted less urgent) | 0.088 |
| Over-triage rate (predicted more urgent) | 0.284 |
| Mistriage rate | 0.372 (study nurses: 0.147) |
| Brier score (mean over levels) | 0.0923 |

Confusion matrix (rows: true level, columns: predicted 1–5):

| true \ predicted | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| **1** | 5 | 36 | 0 | 1 | 0 |
| **2** | 0 | 163 | 22 | 0 | 0 |
| **3** | 0 | 135 | 282 | 47 | 0 |
| **4** | 0 | 5 | 80 | 291 | 0 |
| **5** | 0 | 0 | 11 | 110 | 12 |

Calibration (probability of the chosen level against accuracy):

| Probability | n | Mean probability | Accuracy |
|---|---|---|---|
| 0.0–0.4 | 144 | 0.30 | 0.19 |
| 0.4–0.5 | 349 | 0.46 | 0.50 |
| 0.5–0.6 | 499 | 0.55 | 0.74 |
| 0.6–0.7 | 81 | 0.64 | 0.83 |
| 0.7–0.8 | 118 | 0.74 | 0.90 |
| 0.8–0.9 | 9 | 0.81 | 0.67 |

## Explanations
Each prediction lists the three features that pushed most towards its level (SHAP values of
the uncalibrated logistic_regression).

"""ML-01: train and evaluate the urgency model (plan Section 11).

    python -m training.train [--ktas data/ktas/data.csv] [--out models/urgency-v1.joblib]

Steps: (1) clean impossible and missing values; (2) stratified train/test split;
(3) compare logistic regression (baseline), random forest and gradient boosting with
5-fold cross-validation; (4) class weights for the rare levels 1–2; (5) calibrate the
probabilities and prepare SHAP explanations; (6) save the model file with its version.

Metrics: recall on levels 1–2 (missing an urgent patient is the worst error), under- and
over-triage rates, macro F1, the confusion matrix and a calibration table. Without the
KTAS file the documented synthetic fallback is used, and the model card says so.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from ml.features import FEATURES, features
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from training.data import load_ktas, synthetic

LEVELS = [1, 2, 3, 4, 5]
SEED = 42
TARGET_URGENT_RECALL = 0.90  # missing an urgent patient is the worst error (plan Section 11)
SERVICE = Path(__file__).resolve().parents[1]


def urgent_recall(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Share of truly urgent patients (levels 1–2) the model also calls urgent (1–2)."""
    urgent = y_true <= 2
    return float(np.mean(y_pred[urgent] <= 2)) if urgent.any() else 0.0


def triage_rates(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Under-triage: predicted less urgent than truth (higher level). Over-triage: more urgent."""
    return {
        "under_triage": float(np.mean(y_pred > y_true)),
        "over_triage": float(np.mean(y_pred < y_true)),
        "mistriage": float(np.mean(y_pred != y_true)),
    }


def candidates() -> dict[str, Callable[[], Pipeline]]:
    """Step 3 and 4: three model families, each weighting the rare urgent levels up."""
    return {
        "logistic_regression": lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(class_weight="balanced", max_iter=2000),
        ),
        "random_forest": lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=300, min_samples_leaf=3, class_weight="balanced", random_state=SEED, n_jobs=-1
            ),
        ),
        "gradient_boosting": lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingClassifier(
                class_weight="balanced", max_iter=300, learning_rate=0.06, random_state=SEED
            ),
        ),
    }


@dataclass
class Evaluation:
    name: str
    urgent_recall: float
    macro_f1: float

    @property
    def score(self) -> float:
        """Selection rule: urgent recall and macro F1 weigh equally (both matter; recall most)."""
        return 0.5 * self.urgent_recall + 0.5 * self.macro_f1


def cross_validate(x: np.ndarray, y: np.ndarray) -> list[Evaluation]:
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    results = []
    for name, make in candidates().items():
        pred = cross_val_predict(make(), x, y, cv=folds)
        results.append(Evaluation(name, urgent_recall(y, pred), float(f1_score(y, pred, average="macro"))))
    return results


def decide(probs: np.ndarray, threshold: float) -> np.ndarray:
    """Cost-aware decision on calibrated probabilities: urgent (1–2) when P(1) + P(2) reaches the
    threshold, then the likelier of 1 and 2; otherwise the likeliest of 3–5."""
    urgent = probs[:, 0] + probs[:, 1] >= threshold
    return np.where(urgent, 1 + probs[:, :2].argmax(axis=1), 3 + probs[:, 2:].argmax(axis=1))


def tune_threshold(probs: np.ndarray, y: np.ndarray) -> float:
    """The highest threshold whose out-of-fold urgent recall reaches the target: as few
    over-triaged patients as possible while missing at most 10% of urgent ones."""
    for t in np.round(np.arange(0.60, 0.04, -0.01), 2):
        if urgent_recall(y, decide(probs, float(t))) >= TARGET_URGENT_RECALL:
            return float(t)
    return 0.05


def calibration_table(y_true: np.ndarray, probs: np.ndarray, pred: np.ndarray) -> list[dict[str, float]]:
    """Probability of the chosen level against how often it was right, per band."""
    conf = probs[np.arange(len(pred)), pred - 1]
    correct = pred == y_true
    edges = [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        band = (conf >= lo) & (conf < hi)
        if band.any():
            rows.append(
                {
                    "from": float(lo),
                    "to": min(float(hi), 1.0),
                    "n": int(band.sum()),
                    "mean_confidence": float(conf[band].mean()),
                    "accuracy": float(correct[band].mean()),
                }
            )
    return rows


def train(rows: list[dict[str, Any]], labels: list[int], source: str, version: str) -> dict[str, Any]:
    x = np.array([features(r) for r in rows], dtype=float)
    y = np.array(labels)
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.2, stratify=y, random_state=SEED)
    evaluations = cross_validate(x_train, y_train)
    best = max(evaluations, key=lambda e: e.score)
    base = candidates()[best.name]().fit(x_train, y_train)

    def calibrated() -> Any:
        return CalibratedClassifierCV(candidates()[best.name](), method="sigmoid", cv=5)

    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    oof = cross_val_predict(calibrated(), x_train, y_train, cv=folds, method="predict_proba")
    threshold = tune_threshold(oof, y_train)
    model = calibrated().fit(x_train, y_train)

    probs = model.predict_proba(x_test)
    pred = decide(probs, threshold)
    argmax_pred = np.array(LEVELS)[probs.argmax(axis=1)]
    onehot = np.eye(len(LEVELS))[y_test - 1]
    metrics = {
        "source": source,
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
        "cross_validation": [vars(e) | {"score": e.score} for e in evaluations],
        "selected": best.name,
        "urgent_threshold": threshold,
        "test_plain_argmax": {
            "urgent_recall": urgent_recall(y_test, argmax_pred),
            **triage_rates(y_test, argmax_pred),
        },
        "test": {
            "urgent_recall": urgent_recall(y_test, pred),
            "macro_f1": float(f1_score(y_test, pred, average="macro")),
            **triage_rates(y_test, pred),
            "brier": float(
                np.mean([brier_score_loss(onehot[:, k], probs[:, k]) for k in range(len(LEVELS))])
            ),
            "confusion_matrix": confusion_matrix(y_test, pred, labels=LEVELS).tolist(),
            "calibration": calibration_table(y_test, probs, pred),
        },
        "class_counts": {int(k): int((y == k).sum()) for k in LEVELS},
    }
    background = SimpleImputer(strategy="median").fit_transform(x_train)[:: max(1, len(x_train) // 100)]
    return {
        "version": version,
        "features": list(FEATURES),
        "classes": LEVELS,
        "model": model,
        "explainer_model": base,
        "background": background,
        "trained_on": source,
        "urgent_threshold": threshold,
        "metrics": metrics,
    }


def model_card(artifact: dict[str, Any]) -> str:
    m, t = artifact["metrics"], artifact["metrics"]["test"]
    cm = "\n".join(
        f"| **{lvl}** | " + " | ".join(str(v) for v in row) + " |"
        for lvl, row in zip(LEVELS, t["confusion_matrix"], strict=True)
    )
    cv = "\n".join(
        f"| {e['name']} | {e['urgent_recall']:.3f} | {e['macro_f1']:.3f} | {e['score']:.3f} |"
        for e in m["cross_validation"]
    )
    cal = "\n".join(
        f"| {c['from']:.1f}–{c['to']:.1f} | {c['n']} | {c['mean_confidence']:.2f} | {c['accuracy']:.2f} |"
        for c in t["calibration"]
    )
    synthetic_note = (
        "\n> **Trained on synthetic data** (the documented fallback, risk R6). These numbers show the "
        "pipeline works; they say nothing about clinical accuracy. Put the KTAS study file at "
        "`data/ktas/data.csv` and run the training again to replace them.\n"
        if m["source"].startswith("synthetic")
        else ""
    )
    return f"""# Model card: {artifact["version"]}

Urgency level 1 (most urgent) to 5, KTAS scale. Decision support only, not a medical device:
a nurse always confirms or overrides the level, and safety rules in the pathway (oxygen below 90,
systolic pressure below 80, confidence below 0.7) send the patient to review whatever the model says.
{synthetic_note}
- Data: {m["source"]} · train {m["n_train"]} / test {m["n_test"]} · levels {m["class_counts"]}
- Selected model: **{m["selected"]}** (sigmoid-calibrated, class-weighted)
- Decision rule: urgent (level 1 or 2) when P(1) + P(2) ≥ **{m["urgent_threshold"]:.2f}**, tuned
  on out-of-fold training predictions for urgent recall ≥ {TARGET_URGENT_RECALL:.0%};
  otherwise the likeliest of 3–5. With a plain "most likely level" rule the test urgent
  recall would be {m["test_plain_argmax"]["urgent_recall"]:.3f} (calibration undoes the class
  weights, so the rare urgent levels are rarely the most likely).
- Features: {", ".join(artifact["features"])}

## Cross-validation (5-fold, training set)

| Model | Recall on levels 1–2 | Macro F1 | Selection score |
|---|---|---|---|
{cv}

## Held-out test set

| Metric | Value |
|---|---|
| Recall on levels 1–2 | **{t["urgent_recall"]:.3f}** |
| Macro F1 | {t["macro_f1"]:.3f} |
| Under-triage rate (predicted less urgent) | {t["under_triage"]:.3f} |
| Over-triage rate (predicted more urgent) | {t["over_triage"]:.3f} |
| Mistriage rate | {t["mistriage"]:.3f} (study nurses: 0.147) |
| Brier score (mean over levels) | {t["brier"]:.4f} |

Confusion matrix (rows: true level, columns: predicted 1–5):

| true \\ predicted | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
{cm}

Calibration (probability of the chosen level against accuracy):

| Probability | n | Mean probability | Accuracy |
|---|---|---|---|
{cal}

## Explanations
Each prediction lists the three features that pushed most towards its level (SHAP values of
the uncalibrated {m["selected"]}).
"""


def write_urgency_mix(class_counts: dict[str, int], source: str, version: str, path: Path) -> dict[str, Any]:
    """Plan Section 11: the dataset also gives the Simulator its urgency mix. Written beside the
    simulator's code as data (no run-time link between the services)."""
    total = sum(class_counts.values())
    mix = {
        str(level): round(n / total, 4) for level, n in sorted(class_counts.items(), key=lambda x: int(x[0]))
    }
    mix[max(mix, key=lambda k: mix[k])] += round(1 - sum(mix.values()), 4)  # rounding remainder
    doc = {"source": source, "model_version": version, "records": total, "mix": mix}
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ktas", default=str(SERVICE.parents[1] / "data" / "ktas" / "data.csv"))
    parser.add_argument("--out", default=str(SERVICE / "models" / "urgency-v1.joblib"))
    parser.add_argument("--synthetic-n", type=int, default=6000)
    args = parser.parse_args()
    if Path(args.ktas).exists():
        rows, labels = load_ktas(args.ktas)
        source, version = f"KTAS study file ({len(rows)} records)", "urgency-v1"
    else:
        rows, labels = synthetic(args.synthetic_n)
        source, version = f"synthetic-v1 ({len(rows)} records, seed 7)", "urgency-v1-synthetic"
    artifact = train(rows, labels, source, version)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.out, compress=3)
    docs = SERVICE.parents[1] / "docs" / "ml"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "model-card.md").write_text(model_card(artifact))
    (docs / "metrics.json").write_text(json.dumps(artifact["metrics"], indent=2))
    mix_file = SERVICE.parents[0] / "simulator" / "simulator" / "urgency_mix.json"
    write_urgency_mix(artifact["metrics"]["class_counts"], source, version, mix_file)
    print(
        json.dumps(artifact["metrics"]["test"] | {"selected": artifact["metrics"]["selected"]}, indent=2)[
            :1500
        ]
    )


if __name__ == "__main__":
    main()

"""SIM-05: two simulation runs side by side.

For each metric both 95% intervals, the difference of the means and whether the
intervals overlap. Only when they do not is one scenario called better: overlapping
intervals mean the runs cannot tell the scenarios apart (a conservative test; the
report says so). The changed scenario settings are listed, so the reason for a
difference is visible.
"""

from __future__ import annotations

from typing import Any

# A target[...] metric is the share of patients who waited longer than the target's limit.
LOWER_IS_BETTER = ("wait_mean[", "wait_p95[", "queue[", "deadline_miss[", "target[", "los_mean", "in_system")
HIGHER_IS_BETTER = ("completed",)


def metrics_of(result: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    """A plain simulation's metrics, or those of the staffing the advisor recommended."""
    if not result:
        return {}
    run = result.get("simulation") or (result.get("advice") or {}).get("result") or {}
    metrics: dict[str, dict[str, float]] = run.get("metrics", {})
    return metrics


def direction(metric: str) -> str | None:
    if metric.startswith(LOWER_IS_BETTER):
        return "lower"
    if metric.startswith(HIGHER_IS_BETTER):
        return "higher"
    return None  # e.g. utilisation: neither high nor low is better in itself


def compare_metric(metric: str, a: dict[str, float] | None, b: dict[str, float] | None) -> dict[str, Any]:
    row: dict[str, Any] = {"metric": metric, "a": a, "b": b, "better_is": direction(metric)}
    if a is None or b is None:
        return row | {"difference": None, "distinct": False, "better": None}
    distinct = a["high"] < b["low"] or b["high"] < a["low"]
    better = None
    if distinct and row["better_is"]:
        b_lower = b["mean"] < a["mean"]
        better = "b" if b_lower == (row["better_is"] == "lower") else "a"
    return row | {"difference": b["mean"] - a["mean"], "distinct": distinct, "better": better}


def scenario_changes(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """Settings that differ between the two scenarios (arrivals as a daily total)."""

    def flat(sc: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in sc.items() if k not in ("staff", "arrivals_per_hour")}
        out |= {f"staff[{role}]": n for role, n in (sc.get("staff") or {}).items()}
        out["arrivals_per_day"] = round(sum(sc.get("arrivals_per_hour") or []), 2)
        return out

    fa, fb = flat(a), flat(b)
    return [
        {"setting": k, "a": fa.get(k), "b": fb.get(k)}
        for k in sorted(fa.keys() | fb.keys())
        if fa.get(k) != fb.get(k)
    ]


def compare(job_a: dict[str, Any], job_b: dict[str, Any]) -> dict[str, Any]:
    ma, mb = metrics_of(job_a.get("result")), metrics_of(job_b.get("result"))
    rows = [compare_metric(m, ma.get(m), mb.get(m)) for m in sorted(ma.keys() | mb.keys())]
    return {
        "a": {k: job_a[k] for k in ("id", "pathway", "version", "kind")},
        "b": {k: job_b[k] for k in ("id", "pathway", "version", "kind")},
        "same_pathway_version": (job_a["pathway"], job_a["version"]) == (job_b["pathway"], job_b["version"]),
        "changes": scenario_changes(job_a["scenario"], job_b["scenario"]),
        "metrics": rows,
        "distinct": sum(r["distinct"] for r in rows),
    }

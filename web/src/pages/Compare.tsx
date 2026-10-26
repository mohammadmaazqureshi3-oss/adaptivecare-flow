// SIM-05: two simulation runs side by side. A scenario is only called better for a figure
// when the two 95% intervals do not overlap; otherwise the runs cannot tell them apart.

import { useEffect, useState } from "react";
import { api, type Comparison, type EstimateOut, type MetricComparison } from "../api";

const PERCENT = /^(utilisation|deadline_miss|target)\[/;

function label(metric: string): string {
  const m = metric.match(/^([a-z_0-9]+)(?:\[(.*)\])?$/);
  if (!m) return metric;
  const names: Record<string, string> = {
    wait_mean: "Mean wait",
    wait_p95: "95th percentile wait",
    utilisation: "Utilisation",
    queue: "Queue length",
    deadline_miss: "Missed deadline",
    los_mean: "Length of stay",
    in_system: "Patients in the system",
    completed: "Patients completed",
    arrival_rate_per_min: "Arrivals per minute",
    target: "Target met",
  };
  return `${names[m[1]] ?? m[1]}${m[2] ? ` · ${m[2]}` : ""}`;
}

function value(metric: string, e: EstimateOut | null): string {
  if (!e) return "—";
  const pct = PERCENT.test(metric);
  // Rounding can give "-0" for tiny negative interval ends; show it as 0.
  const f = (x: number) => (pct ? `${(x * 100).toFixed(0)}%` : x.toFixed(1)).replace(/^-(0(\.0)?%?)$/, "$1");
  return `${f(e.mean)} [${f(e.low)}–${f(e.high)}]`;
}

function verdict(r: MetricComparison): string {
  if (!r.a || !r.b) return "only in one run";
  if (!r.distinct) return "no clear difference";
  if (!r.better) return "different";
  return `#${r.better === "a" ? "A" : "B"} better`;
}

export function CompareRuns({ a, b, onClose }: { a: number; b: number; onClose: () => void }) {
  const [c, setC] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .compareSimulations(a, b)
      .then(setC)
      .catch((e) => setError(e.message));
  }, [a, b]);
  if (error) return <p className="error">{error}</p>;
  if (!c) return <p className="muted">Comparing…</p>;
  return (
    <section className="card compare">
      <div className="row-form">
        <h3 className="grow">
          Run A #{c.a.id} ({c.a.kind}) vs run B #{c.b.id} ({c.b.kind})
        </h3>
        <button className="ghost" onClick={onClose}>
          Close
        </button>
      </div>
      {!c.same_pathway_version && <p className="hints">The runs simulate different pathway versions.</p>}
      <p className="muted small">
        {c.changes.length === 0
          ? "Same scenario settings."
          : `Changed: ${c.changes.map((x) => `${x.setting} ${String(x.a ?? "–")} → ${String(x.b ?? "–")}`).join("; ")}.`}{" "}
        {c.distinct} of {c.metrics.length} figures differ beyond their 95% intervals.
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>Figure</th>
            <th>A #{c.a.id}</th>
            <th>B #{c.b.id}</th>
            <th>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {c.metrics.map((r) => (
            <tr key={r.metric} className={r.better ? `better-${r.better}` : ""}>
              <td>{label(r.metric)}</td>
              <td>{value(r.metric, r.a)}</td>
              <td>{value(r.metric, r.b)}</td>
              <td className={r.distinct ? "" : "muted"}>{verdict(r)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

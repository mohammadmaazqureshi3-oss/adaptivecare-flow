// Algorithm 3 in the IDE: describe a scenario, run the Simulator (SIM-01/02), optionally ask
// the Staffing Advisor (SIM-03), and read every figure with its 95% confidence interval.

import { useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type EstimateOut,
  type ScenarioIn,
  type SimulationJob,
  type SimulationResult,
  type TargetIn,
  type User,
  type Version,
} from "../api";

const fmt = (x: number, digits = 1) => (Number.isFinite(x) ? x.toFixed(digits) : "—");

function Ci({ e, unit = "", pct = false }: { e?: EstimateOut; unit?: string; pct?: boolean }) {
  if (!e) return <span className="muted">—</span>;
  const k = pct ? 100 : 1;
  const d = pct ? 0 : 1;
  return (
    <span title={`95% CI ${fmt(e.low * k, d)}–${fmt(e.high * k, d)}`}>
      {fmt(e.mean * k, d)}
      {unit} <span className="muted small">[{fmt(e.low * k, d)}–{fmt(e.high * k, d)}]</span>
    </span>
  );
}

function UtilBar({ e }: { e?: EstimateOut }) {
  if (!e) return null;
  const clamp = (x: number) => Math.max(0, Math.min(1, x)) * 100;
  const hot = e.mean >= 0.85 ? "hot" : e.mean >= 0.7 ? "warm" : "";
  return (
    <div className="util" aria-label={`utilisation ${Math.round(e.mean * 100)}%`}>
      <div className={`util-fill ${hot}`} style={{ width: `${clamp(e.mean)}%` }} />
      <div className="util-ci" style={{ left: `${clamp(e.low)}%`, width: `${clamp(e.high) - clamp(e.low)}%` }} />
    </div>
  );
}

function Results({ job }: { job: SimulationJob }) {
  const r = job.result!;
  const sim: SimulationResult | null | undefined = r.simulation ?? r.advice?.result;
  const m = sim?.metrics ?? {};
  const deadlines = Object.keys(m).filter((k) => k.startsWith("deadline_miss["));
  const bottleneck = r.roles.length > 1
    ? r.roles.reduce((a, b) => ((m[`utilisation[${a}]`]?.mean ?? 0) >= (m[`utilisation[${b}]`]?.mean ?? 0) ? a : b))
    : null;

  return (
    <div className="sim-results">
      {r.advice && (
        <div className={`card advice ${r.advice.feasible ? "ok" : "bad"}`}>
          <h3>Staffing Advisor</h3>
          {r.advice.feasible ? (
            <p>
              Recommended:{" "}
              {Object.entries(r.advice.staff)
                .map(([role, n]) => `${n} ${role}`)
                .join(", ")}{" "}
              · cost {fmt(r.advice.cost, 1)}. Every target is met at the upper end of its 95% interval.
            </p>
          ) : (
            <p>{r.advice.reason}.</p>
          )}
          <details>
            <summary>{r.advice.rounds.length} search rounds (greedy: one more person where it helps most per cost)</summary>
            <table className="table compact">
              <thead>
                <tr>
                  <th>Staff</th>
                  <th>Cost</th>
                  <th>Shortfall</th>
                </tr>
              </thead>
              <tbody>
                {r.advice.rounds.map((round, i) => (
                  <tr key={i}>
                    <td>
                      {Object.entries(round.staff)
                        .map(([role, n]) => `${n} ${role}`)
                        .join(", ")}
                    </td>
                    <td>{fmt(round.cost, 1)}</td>
                    <td>{fmt(round.shortfall, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}
      {sim && (
        <>
          <p className="muted small">
            {sim.replications} replications{sim.cap_reached ? " (cap reached: intervals are wider than 5%)" : ", each interval within 5% of its mean"}
            . Mean [95% interval].
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Utilisation</th>
                <th />
                <th>Mean wait</th>
                <th>95th percentile wait</th>
                <th>Queue length</th>
              </tr>
            </thead>
            <tbody>
              {r.roles.map((role) => (
                <tr key={role}>
                  <td>
                    {role} {role === bottleneck && <span className="badge badge-unsafe">bottleneck</span>}
                  </td>
                  <td>
                    <Ci e={m[`utilisation[${role}]`]} pct unit="%" />
                  </td>
                  <td className="util-cell">
                    <UtilBar e={m[`utilisation[${role}]`]} />
                  </td>
                  <td>
                    <Ci e={m[`wait_mean[${role}]`]} unit=" min" />
                  </td>
                  <td>
                    <Ci e={m[`wait_p95[${role}]`]} unit=" min" />
                  </td>
                  <td>
                    <Ci e={m[`queue[${role}]`]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="sim-grid">
            <div className="card">
              <h3>Deadline targets</h3>
              {r.targets.length === 0 && <p className="muted small">No targets set.</p>}
              {r.targets.map((t) => {
                const e = m[t.metric];
                const ok = e ? e.high <= t.limit : false;
                return (
                  <div key={t.metric} className="target-row">
                    <span className={`badge ${ok ? "badge-safe" : "badge-unsafe"}`}>{ok ? "met" : "missed"}</span>
                    <span className="small">
                      {t.text}: <Ci e={e} pct unit="%" />
                    </span>
                  </div>
                );
              })}
            </div>
            <div className="card">
              <h3>Missed deadlines per task</h3>
              {deadlines.length === 0 && <p className="muted small">No task has a deadline.</p>}
              {deadlines.map((k) => (
                <div key={k} className="small">
                  {k.slice(14, -1)}: <Ci e={m[k]} pct unit="%" />
                </div>
              ))}
              <h3 className="spaced">Length of stay</h3>
              <div className="small">
                <Ci e={m["los_mean"]} unit=" min" />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export function Simulate({ pathwayId, user }: { pathwayId: string; user: User }) {
  const [version, setVersion] = useState<Version | null>(null);
  const [rate, setRate] = useState("6");
  const [profile, setProfile] = useState("");
  const [staff, setStaff] = useState<Record<string, number>>({});
  const [cost, setCost] = useState<Record<string, number>>({});
  const [days, setDays] = useState(7);
  const [warmup, setWarmup] = useState(1);
  const [seed, setSeed] = useState(1);
  const [targets, setTargets] = useState<TargetIn[]>([]);
  const [advise, setAdvise] = useState(false);
  const [budget, setBudget] = useState(20);
  const [job, setJob] = useState<SimulationJob | null>(null);
  const [history, setHistory] = useState<SimulationJob[]>([]);
  const [issues, setIssues] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .versions(pathwayId)
      .then((list) => api.version(list[list.length - 1].id))
      .then((v) => {
        setVersion(v);
        const roles = [...new Set(v.model.nodes.filter((n) => n.type === "task" && n.kind === "human" && n.role).map((n) => n.role!))];
        setStaff(Object.fromEntries(roles.map((r) => [r, 2])));
        setCost(Object.fromEntries(roles.map((r) => [r, 1])));
        const confirm = v.model.nodes.find((n) => n.id === "confirm");
        if (confirm) setTargets([{ task: "confirm", max_wait_min: 5, max_share: 0.05, urgency_max: 2 }]);
        return api.simulations(v.id);
      })
      .then(setHistory)
      .catch((e) => setError(e.message));
  }, [pathwayId]);

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") return;
    const t = setTimeout(() => api.simulation(job.id).then(setJob).catch((e) => setError(e.message)), 800);
    return () => clearTimeout(t);
  }, [job]);

  useEffect(() => {
    if (job?.status === "done" && version) api.simulations(version.id).then(setHistory).catch(() => undefined);
  }, [job?.status, version]);

  const humanTasks = useMemo(
    () => version?.model.nodes.filter((n) => n.type === "task" && n.kind === "human") ?? [],
    [version],
  );

  async function run() {
    if (!version) return;
    setError(null);
    setIssues([]);
    let arrivals: number | number[] = Number(rate);
    if (profile.trim()) {
      arrivals = profile.split(/[\s,]+/).filter(Boolean).map(Number);
      if (arrivals.length !== 24 || arrivals.some((x) => Number.isNaN(x) || x < 0)) {
        setError("The daily profile needs 24 non-negative numbers, one per hour.");
        return;
      }
    }
    const scenario: ScenarioIn = { arrivals_per_hour: arrivals, staff, cost, days, warmup_days: warmup, seed, targets };
    try {
      setJob(await api.startSimulation(version.id, { scenario, advise, budget: advise ? budget : null }));
    } catch (err) {
      if (err instanceof ApiError && err.detail && typeof err.detail === "object" && "issues" in err.detail) {
        setIssues((err.detail as { issues: string[] }).issues);
      } else setError(err instanceof Error ? err.message : "Could not start the simulation");
    }
  }

  if (!version) return <div className="page">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</div>;
  const running = job && (job.status === "queued" || job.status === "running");

  return (
    <div className="page wide">
      <div className="inline">
        <a href={`#/pathways/${pathwayId}`} className="ghost">
          ← Editor
        </a>
        <h2 className="flush">
          Simulate {version.model.name || pathwayId} · v{version.number}
        </h2>
      </div>
      <p className="muted small">
        Virtual patients run through the same token rules as the Engine, with your task durations and branch
        probabilities. Validated against Erlang C and Little's law.
      </p>

      <div className="card sim-form">
        <div className="row-form">
          <label>
            Arrivals per hour
            <input type="number" min={0} step="0.5" value={rate} onChange={(e) => setRate(e.target.value)} disabled={!!profile.trim()} />
          </label>
          <label className="grow">
            or a daily profile (24 values, hour 0 to 23)
            <input value={profile} placeholder="2,1,1,1,1,2,4,6,8,9,9,8,8,8,7,7,7,8,8,7,6,5,4,3" onChange={(e) => setProfile(e.target.value)} />
          </label>
          <label>
            Days
            <input type="number" min={1} value={days} onChange={(e) => setDays(Number(e.target.value))} />
          </label>
          <label>
            Warm-up days
            <input type="number" min={0} step="0.5" value={warmup} onChange={(e) => setWarmup(Number(e.target.value))} />
          </label>
          <label>
            Seed
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
          </label>
        </div>
        <div className="row-form">
          {Object.keys(staff).map((role) => (
            <fieldset key={role} className="role-box">
              <legend>{role}</legend>
              <label>
                Staff
                <input type="number" min={0} value={staff[role]} onChange={(e) => setStaff({ ...staff, [role]: Number(e.target.value) })} />
              </label>
              <label>
                Cost weight
                <input type="number" min={0} step="0.5" value={cost[role]} onChange={(e) => setCost({ ...cost, [role]: Number(e.target.value) })} />
              </label>
            </fieldset>
          ))}
        </div>
        <h3>Deadline targets</h3>
        {targets.map((t, i) => (
          <div className="inline target-edit" key={i}>
            <span className="small">At most</span>
            <input type="number" className="short" min={0} max={100} value={Math.round(t.max_share * 100)}
              onChange={(e) => setTargets(targets.map((x, j) => (j === i ? { ...x, max_share: Number(e.target.value) / 100 } : x)))} />
            <span className="small">% of</span>
            <select value={t.urgency_max ?? ""} onChange={(e) => setTargets(targets.map((x, j) => (j === i ? { ...x, urgency_max: e.target.value ? Number(e.target.value) : null } : x)))}>
              <option value="">all patients</option>
              <option value="1">urgency 1</option>
              <option value="2">urgency 1–2</option>
              <option value="3">urgency 1–3</option>
            </select>
            <span className="small">wait more than</span>
            <input type="number" className="short" min={0} value={t.max_wait_min}
              onChange={(e) => setTargets(targets.map((x, j) => (j === i ? { ...x, max_wait_min: Number(e.target.value) } : x)))} />
            <span className="small">min for</span>
            <select value={t.task} onChange={(e) => setTargets(targets.map((x, j) => (j === i ? { ...x, task: e.target.value } : x)))}>
              {humanTasks.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label || n.id}
                </option>
              ))}
            </select>
            <button className="ghost" onClick={() => setTargets(targets.filter((_, j) => j !== i))}>
              ✕
            </button>
          </div>
        ))}
        <button className="ghost fit" disabled={!humanTasks.length}
          onClick={() => setTargets([...targets, { task: humanTasks[0].id, max_wait_min: 10, max_share: 0.1, urgency_max: null }])}>
          + target
        </button>
        <div className="row-form spaced">
          <label className="check">
            <input type="checkbox" checked={advise} onChange={(e) => setAdvise(e.target.checked)} />
            Find the cheapest staffing that meets every target (Staffing Advisor)
          </label>
          {advise && (
            <label>
              Budget (cost units)
              <input type="number" min={0} value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
            </label>
          )}
          <span className="spacer" />
          <button className="primary" onClick={run} disabled={!!running || user.role === "admin"}>
            {running ? "Running…" : advise ? "Simulate and advise" : "Simulate"}
          </button>
        </div>
      </div>

      {issues.length > 0 && (
        <div className="hints card">
          <strong>Not ready to simulate (DES-06):</strong>
          {issues.map((i) => (
            <div key={i}>⚠ {i}</div>
          ))}
          <div className="small">Set durations and branch probabilities on the tasks and decisions in the editor.</div>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {running && <p className="muted">Simulating… replications run in the background.</p>}
      {job?.status === "failed" && <p className="error">The simulation failed: {job.error}</p>}
      {job?.status === "done" && <Results job={job} />}

      {history.length > 0 && (
        <details className="spaced">
          <summary>Earlier runs of this version ({history.length})</summary>
          <ul className="history">
            {history.map((h) => (
              <li key={h.id}>
                <button className="ghost" onClick={() => setJob(h)}>
                  #{h.id} · {h.kind} · {new Date(h.created_at).toLocaleString()} · {h.status}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

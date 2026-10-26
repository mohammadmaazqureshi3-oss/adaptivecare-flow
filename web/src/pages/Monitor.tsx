// Monitoring for managers, admins and doctors (plan Section 10 matrix):
// MON-02 dashboard (managers, admins), MON-01 case history (admins, doctors, managers),
// MON-03 service health and metrics (admins).

import { useEffect, useState } from "react";
import {
  api,
  type CaseDetail,
  type CaseSummary,
  type ServiceStatus,
  type User,
} from "../api";
import { describe, minutes, tone } from "../monitor/describe";

type Tab = "dashboard" | "cases" | "services";

export function tabsFor(role: string): Tab[] {
  if (role === "admin") return ["dashboard", "cases", "services"];
  if (role === "manager") return ["dashboard", "cases"];
  if (role === "doctor") return ["cases"];
  return [];
}

const TITLES: Record<Tab, string> = { dashboard: "Dashboard", cases: "Cases", services: "Services" };

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "–";
}

function usePolling<T>(load: () => Promise<T>, deps: unknown[], everyMs = 10000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const run = () =>
      load()
        .then((d) => live && (setData(d), setError(null)))
        .catch((e) => live && setError(e.message));
    run();
    const timer = setInterval(run, everyMs);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, deps);
  return { data, error };
}

export function Monitor({ user, tab, caseId }: { user: User; tab?: string; caseId?: string }) {
  const tabs = tabsFor(user.role);
  const current: Tab = tabs.includes(tab as Tab) ? (tab as Tab) : tabs[0];
  return (
    <div className="page">
      <div className="row-form">
        <h2 className="grow">Monitoring</h2>
        <nav className="tabs">
          {tabs.map((t) => (
            <a key={t} className={t === current ? "active" : ""} href={`#/monitor/${t}`}>
              {TITLES[t]}
            </a>
          ))}
        </nav>
      </div>
      {current === "dashboard" && <DashboardView />}
      {current === "cases" && !caseId && <CasesView />}
      {current === "cases" && caseId && <CaseView key={caseId} id={caseId} />}
      {current === "services" && <ServicesView />}
    </div>
  );
}

function Tile({ label, value, note, bad }: { label: string; value: string; note?: string; bad?: boolean }) {
  return (
    <div className={`tile${bad ? " tile-bad" : ""}`}>
      <span className="muted small">{label}</span>
      <strong>{value}</strong>
      {note && <span className="muted small">{note}</span>}
    </div>
  );
}

function DashboardView() {
  const [hours, setHours] = useState(24);
  const { data: d, error } = usePolling(() => api.dashboard(hours), [hours]);
  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const active = Object.values(d.active_cases).reduce((a, b) => a + b, 0);
  const ended = Object.values(d.ended_cases).reduce((a, b) => a + b, 0);
  const rate = d.deadlines.missed_rate;
  return (
    <>
      <div className="row-form">
        <label>
          Period
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            <option value={8}>Last 8 hours</option>
            <option value={24}>Last 24 hours</option>
            <option value={168}>Last 7 days</option>
          </select>
        </label>
        <span className="muted small grow">Updated {when(d.at)}; refreshes every 10 seconds.</span>
      </div>
      <div className="tiles">
        <Tile
          label="Active cases"
          value={String(active)}
          note={Object.entries(d.active_cases).map(([p, n]) => `${p} ${n}`).join(" · ") || "none"}
        />
        <Tile
          label="Cases ended"
          value={String(ended)}
          note={Object.entries(d.ended_cases).map(([s, n]) => `${s} ${n}`).join(" · ") || "none"}
        />
        <Tile
          label="Missed deadlines"
          value={rate === null ? "–" : `${Math.round(rate * 100)}%`}
          note={`${d.deadlines.missed} of ${d.deadlines.with_deadline} tasks with a deadline`}
          bad={rate !== null && rate > 0.1}
        />
        <Tile label="Escalated tasks" value={String(d.deadlines.escalated)} bad={d.deadlines.escalated > 0} />
      </div>
      <div className="two-col">
        <section>
          <h3>Queues now</h3>
          {Object.keys(d.queues).length === 0 ? (
            <p className="muted">No open tasks.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Open</th>
                  <th>Oldest</th>
                  <th>Overdue</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(d.queues).map(([role, q]) => (
                  <tr key={role}>
                    <td>{role}</td>
                    <td>{q.open}</td>
                    <td>{minutes(q.oldest_min)}</td>
                    <td className={q.overdue ? "error" : ""}>{q.overdue}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <section>
          <h3>Waits until someone takes a task</h3>
          {Object.keys(d.waits).length === 0 ? (
            <p className="muted">No tasks taken in this period.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Taken</th>
                  <th>Mean</th>
                  <th>90% within</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(d.waits).map(([role, w]) => (
                  <tr key={role}>
                    <td>{role}</td>
                    <td>{w.claimed}</td>
                    <td>{minutes(w.mean_min)}</td>
                    <td>{minutes(w.p90_min)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </>
  );
}

function CasesView() {
  const [status, setStatus] = useState("");
  const [pathway, setPathway] = useState("");
  const [patient, setPatient] = useState("");
  const { data, error } = usePolling(
    () => api.cases({ status, pathway: pathway.trim(), patient: patient.trim() }),
    [status, pathway, patient],
  );
  return (
    <>
      <div className="row-form">
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any</option>
            {["running", "completed", "failed", "compensated", "cancelled"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          Pathway
          <input value={pathway} placeholder="triage" onChange={(e) => setPathway(e.target.value)} />
        </label>
        <label>
          Patient record number
          <input value={patient} placeholder="P000001" onChange={(e) => setPatient(e.target.value)} />
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      {data === null ? (
        <p className="muted">Loading…</p>
      ) : data.length === 0 ? (
        <p className="muted">No cases yet. Registering a patient starts one.</p>
      ) : (
        <CaseTable cases={data} />
      )}
    </>
  );
}

function CaseTable({ cases, current }: { cases: CaseSummary[]; current?: string }) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Started</th>
          <th>Pathway</th>
          <th>Patient</th>
          <th>Status</th>
          <th>Events</th>
        </tr>
      </thead>
      <tbody>
        {cases.map((c) => (
          <tr
            key={c.case_id}
            className={c.case_id === current ? "selected" : "clickable"}
            onClick={() => (window.location.hash = `/monitor/cases/${c.case_id}`)}
          >
            <td>{when(c.started_at)}</td>
            <td>
              {c.pathway} v{c.version}
            </td>
            <td className="mono">{c.patient_id || "–"}</td>
            <td>
              <span className={`badge badge-case-${c.status}`}>{c.status}</span>
              {c.reason && <span className="muted small"> {c.reason}</span>}
            </td>
            <td>{c.events}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CaseView({ id }: { id: string }) {
  const { data: c, error } = usePolling<CaseDetail>(() => api.caseDetail(id), [id], 5000);
  if (error) return <p className="error">{error}</p>;
  if (!c) return <p className="muted">Loading…</p>;
  return (
    <>
      <p>
        <a href="#/monitor/cases">← All cases</a>
      </p>
      <div className="card">
        <h3>
          {c.pathway} v{c.version} · <span className="mono">{c.patient_id || "no patient"}</span> ·{" "}
          <span className={`badge badge-case-${c.status}`}>{c.status}</span>
        </h3>
        <p className="muted small">
          Case <span className="mono">{c.case_id}</span> · started {when(c.started_at)}
          {c.ended_at && ` · ended ${when(c.ended_at)}`}
          {c.reason && ` · ${c.reason}`}
        </p>
      </div>
      {c.journey.length > 1 && (
        <section>
          <h3>The patient's journey</h3>
          <CaseTable cases={c.journey} current={c.case_id} />
        </section>
      )}
      <section>
        <h3>History ({c.history.length} events)</h3>
        <ol className="timeline">
          {c.history.map((e) => (
            <li key={e.id} className={`tl-${tone(e)}`}>
              <span className="muted small">
                {new Date(e.at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span>{describe(e)}</span>
              <code className="muted small">{e.type}</code>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

function ServicesView() {
  const { data, error } = usePolling<ServiceStatus[]>(() => api.services(), []);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <>
      <p className="muted small">
        Each service also serves <code>/metrics</code> for Prometheus (<code>docker compose --profile monitoring up</code>).
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>Service</th>
            <th>Status</th>
            <th>Up for</th>
            <th>Requests</th>
            <th>Server errors</th>
            <th>p95</th>
            <th>Other</th>
          </tr>
        </thead>
        <tbody>
          {data.map((s) => (
            <tr key={s.service}>
              <td>{s.service}</td>
              <td>
                <span className={`badge ${s.status === "ok" ? "badge-safe" : "badge-unsafe"}`}>{s.status}</span>
              </td>
              <td>{s.uptime_s === undefined ? "–" : minutes(s.uptime_s / 60)}</td>
              <td>{s.requests ?? "–"}</td>
              <td className={s.server_errors ? "error" : ""}>{s.server_errors ?? "–"}</td>
              <td>{s.p95_ms === null || s.p95_ms === undefined ? "–" : `≤ ${s.p95_ms} ms`}</td>
              <td className="small muted">
                {Object.entries(s.gauges ?? {})
                  .map(([k, v]) => `${k.replace(/^[a-z]+_/, "").replace(/_/g, " ")} ${v}`)
                  .join(" · ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

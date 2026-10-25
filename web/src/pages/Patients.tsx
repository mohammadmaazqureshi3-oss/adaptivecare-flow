// PAT-01: as a nurse, I register and search patients.
// Registering will start a case on the matching deployed pathway from Sprint 3 (ENG-01).

import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type ArrivalMode, type Patient, type PatientIn, type Sex } from "../api";

const SEXES: [Sex, string][] = [
  ["female", "Female"],
  ["male", "Male"],
  ["other", "Other"],
  ["unknown", "Unknown"],
];
const ARRIVALS: [ArrivalMode, string][] = [
  ["walk_in", "Walk-in"],
  ["ambulance", "Ambulance"],
  ["referral", "Referral"],
  ["other", "Other"],
];
const EMPTY: PatientIn = { name: "", date_of_birth: "", sex: "unknown", arrival_mode: "walk_in", chief_complaint: "" };

function arrivedText(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function Patients() {
  const [form, setForm] = useState<PatientIn>(EMPTY);
  const [duplicates, setDuplicates] = useState<Patient[] | null>(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Patient[] | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      api
        .searchPatients(q)
        .then((r) => live && setResults(r))
        .catch((e) => live && setNotice({ kind: "error", text: e.message }));
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [q, refresh]);

  async function submit(confirmDuplicate: boolean) {
    setBusy(true);
    setNotice(null);
    try {
      const p = await api.registerPatient({ ...form, confirm_duplicate: confirmDuplicate });
      setNotice({ kind: "info", text: `${p.name} registered as ${p.mrn}.` });
      setForm(EMPTY);
      setDuplicates(null);
      setQ("");
      setRefresh((n) => n + 1);
    } catch (err) {
      const detail = err instanceof ApiError ? (err.detail as { matches?: Patient[] } | undefined) : undefined;
      if (err instanceof ApiError && err.status === 409 && detail?.matches) setDuplicates(detail.matches);
      else setNotice({ kind: "error", text: err instanceof Error ? err.message : "Registration failed" });
    } finally {
      setBusy(false);
    }
  }

  const today = new Date().toISOString().slice(0, 10);

  return (
    <div className="page">
      <h2>Patients</h2>
      <form
        className="card patient-form"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          submit(false);
        }}
      >
        <h3>Register a patient</h3>
        <div className="row-form">
          <label className="grow">
            Full name
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required maxLength={200} />
          </label>
          <label>
            Date of birth
            <input
              type="date"
              max={today}
              value={form.date_of_birth}
              onChange={(e) => setForm({ ...form, date_of_birth: e.target.value })}
              required
            />
          </label>
          <label>
            Sex
            <select value={form.sex} onChange={(e) => setForm({ ...form, sex: e.target.value as Sex })}>
              {SEXES.map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            Arrival
            <select
              value={form.arrival_mode}
              onChange={(e) => setForm({ ...form, arrival_mode: e.target.value as ArrivalMode })}
            >
              {ARRIVALS.map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="row-form">
          <label className="grow">
            Chief complaint
            <input
              value={form.chief_complaint}
              maxLength={200}
              placeholder="e.g. chest pain"
              onChange={(e) => setForm({ ...form, chief_complaint: e.target.value })}
            />
          </label>
          <button className="primary" disabled={busy}>
            Register
          </button>
        </div>
        {duplicates && (
          <div className="duplicate">
            <strong>Possible duplicate.</strong> A patient with this name and date of birth is already registered:
            <ul>
              {duplicates.map((d) => (
                <li key={d.id}>
                  <code>{d.mrn}</code> {d.name}, arrived {arrivedText(d.arrived_at)}
                </li>
              ))}
            </ul>
            <div className="inline">
              <button type="button" className="ghost" onClick={() => setDuplicates(null)}>
                Cancel, it is the same person
              </button>
              <button type="button" className="danger-solid" disabled={busy} onClick={() => submit(true)}>
                Register as a different person
              </button>
            </div>
          </div>
        )}
      </form>
      {notice && <div className={`notice-inline ${notice.kind}`}>{notice.text}</div>}

      <div className="row-form">
        <label className="grow">
          Search
          <input
            type="search"
            value={q}
            placeholder="Name or record number (P000042)"
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
      </div>
      {results === null ? (
        <p className="muted">Loading…</p>
      ) : results.length === 0 ? (
        <p className="muted">{q ? "No patient matches." : "No patients registered yet."}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Record</th>
              <th>Name</th>
              <th>Age</th>
              <th>Sex</th>
              <th>Arrival</th>
              <th>Chief complaint</th>
              <th>Arrived</th>
            </tr>
          </thead>
          <tbody>
            {results.map((p) => (
              <tr key={p.id}>
                <td>
                  <code>{p.mrn}</code>
                </td>
                <td>{p.name}</td>
                <td>{p.age}</td>
                <td>{SEXES.find(([v]) => v === p.sex)?.[1]}</td>
                <td>{ARRIVALS.find(([v]) => v === p.arrival_mode)?.[1]}</td>
                <td>{p.chief_complaint || <span className="muted">—</span>}</td>
                <td className="muted">{arrivedText(p.arrived_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

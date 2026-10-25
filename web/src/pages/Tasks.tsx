// WRK-01: tasks for my role. Claim one, enter the outputs the pathway needs, complete it;
// the engine then moves the case on and the next task appears here.

import { useCallback, useEffect, useState } from "react";
import { api, type Task, type User } from "../api";

const REFRESH_MS = 3000;

function minutesLeft(t: Task, now: number): number | null {
  if (t.due_at) return Math.round((new Date(t.due_at).getTime() - now) / 60_000);
  if (t.deadline_min == null) return null;
  const due = new Date(t.created_at).getTime() + t.deadline_min * 60_000;
  return Math.round((due - now) / 60_000);
}

function Due({ task, now }: { task: Task; now: number }) {
  const left = minutesLeft(task, now);
  if (left == null) return null;
  const cls = left < 0 ? "due overdue" : left <= 2 ? "due soon" : "due";
  return <span className={cls}>{left < 0 ? `${-left} min overdue` : `due in ${left} min`}</span>;
}

function Value({ v }: { v: unknown }) {
  return <code>{v === null || v === undefined ? "—" : String(v)}</code>;
}

function CompleteForm({ task, onDone }: { task: Task; onDone: (msg: string) => void }) {
  const [values, setValues] = useState<Record<string, string | boolean>>(() =>
    Object.fromEntries(task.outputs.map((o) => [o.name, o.type === "bool" ? false : ""])),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  // WRK-02: changing the suggestion (e.g. the ML urgency) needs a reason, which is logged.
  const suggested = task.override ? task.inputs[task.override.suggested] : undefined;
  const decidedRaw = task.override ? values[task.override.decided] : undefined;
  const overriding =
    task.override != null && decidedRaw !== "" && decidedRaw !== undefined && String(decidedRaw) !== String(suggested);

  async function reportProblem() {
    if (!problem || problem.trim().length < 5) {
      setError("Say what went wrong (at least a few words).");
      return;
    }
    setBusy(true);
    try {
      await api.failTask(task.id, problem);
      onDone(`Problem reported for ${task.label}: the pathway takes its fallback or undoes finished steps.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not report the problem");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    const outputs: Record<string, unknown> = {};
    for (const o of task.outputs) {
      const raw = values[o.name];
      if (o.type === "bool") outputs[o.name] = raw === true;
      else if (o.type === "string") outputs[o.name] = String(raw).trim();
      else {
        const n = Number(raw);
        if (raw === "" || Number.isNaN(n) || (o.type === "int" && !Number.isInteger(n))) {
          setError(`${o.name} must be ${o.type === "int" ? "a whole number" : "a number"}`);
          return;
        }
        outputs[o.name] = n;
      }
    }
    setBusy(true);
    setError(null);
    try {
      if (overriding && reason.trim().length < 5) {
        setError(`Changing the suggested ${task.override!.suggested} (${String(suggested)}) needs a reason.`);
        setBusy(false);
        return;
      }
      await api.completeTask(task.id, outputs, overriding ? reason : undefined);
      onDone(`${task.label} completed for ${task.patient_id}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not complete the task");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="complete-form">
      {task.outputs.map((o) => (
        <label key={o.name} className={o.type === "bool" ? "check" : ""}>
          {o.type === "bool" ? (
            <>
              <input
                type="checkbox"
                checked={values[o.name] === true}
                onChange={(e) => setValues({ ...values, [o.name]: e.target.checked })}
              />
              {o.name}
            </>
          ) : (
            <>
              <span>
                {o.name} <span className="muted small">({o.type})</span>
              </span>
              <input
                type={o.type === "string" ? "text" : "number"}
                step={o.type === "float" ? "any" : "1"}
                value={String(values[o.name])}
                onChange={(e) => setValues({ ...values, [o.name]: e.target.value })}
              />
            </>
          )}
        </label>
      ))}
      {task.outputs.length === 0 && <p className="muted small">This task records no values.</p>}
      <button className="primary" disabled={busy} onClick={submit}>
        Complete
      </button>
      <button className="ghost" disabled={busy} onClick={() => setProblem(problem === null ? "" : null)}>
        Report a problem
      </button>
      {overriding && (
        <label className="override">
          <span>
            Reason for changing the suggested {task.override!.suggested} ({String(suggested)}): required, logged
          </span>
          <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      {problem !== null && (
        <label className="override">
          <span>What went wrong? The pathway takes its fallback, or undoes the steps already done.</span>
          <textarea rows={2} value={problem} onChange={(e) => setProblem(e.target.value)} />
          <button className="danger-solid fit" disabled={busy} onClick={reportProblem}>
            Report the problem
          </button>
        </label>
      )}
      {error && <p className="error small">{error}</p>}
    </div>
  );
}

export function Tasks({ user }: { user: User }) {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(() => {
    api
      .tasks()
      .then((t) => {
        setTasks(t);
        setNow(Date.now());
      })
      .catch((e) => setNotice({ kind: "error", text: e.message }));
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  async function act(action: () => Promise<unknown>, done?: string) {
    setNotice(null);
    try {
      await action();
      if (done) setNotice({ kind: "info", text: done });
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Request failed" });
    }
    load();
  }

  const mine = tasks?.filter((t) => t.status === "claimed" && t.assignee === user.email) ?? [];
  const open = tasks?.filter((t) => t.status === "open") ?? [];

  return (
    <div className="page">
      <h2>My tasks</h2>
      <p className="muted small">
        Tasks for the <strong>{user.role}</strong> role, from every running case. The list refreshes every few seconds.
      </p>
      {notice && <div className={`notice-inline ${notice.kind}`}>{notice.text}</div>}
      {tasks === null && <p className="muted">Loading…</p>}

      {mine.length > 0 && <h3>Claimed by me</h3>}
      {mine.map((t) => (
        <div key={t.id} className="card task claimed">
          <div className="task-head">
            <strong>{t.label}</strong>
            <code>{t.patient_id}</code>
            <span className="muted small">
              {t.pathway} v{t.version}
            </span>
            <Due task={t} now={now} />
            <span className="spacer" />
            <button className="ghost" onClick={() => act(() => api.releaseTask(t.id))}>
              Release
            </button>
          </div>
          {typeof t.inputs.triage_note === "string" && <div className="ml-note">{t.inputs.triage_note}</div>}
          {Object.keys(t.inputs).length > 0 && (
            <div className="task-inputs small">
              {Object.entries(t.inputs)
                .filter(([k]) => k !== "triage_note")
                .map(([k, v]) => (
                  <span key={k}>
                    {k}: <Value v={v} />
                  </span>
                ))}
            </div>
          )}
          <CompleteForm task={t} onDone={(msg) => act(async () => undefined, msg)} />
        </div>
      ))}

      <h3>Open</h3>
      {tasks !== null && open.length === 0 && <p className="muted">No open tasks for your role.</p>}
      {open.map((t) => (
        <div key={t.id} className="card task">
          <div className="task-head">
            <strong>{t.label}</strong>
            <code>{t.patient_id}</code>
            <span className="muted small">
              {t.pathway} v{t.version}
            </span>
            <Due task={t} now={now} />
            <span className="spacer" />
            <button className="primary" onClick={() => act(() => api.claimTask(t.id))}>
              Claim
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

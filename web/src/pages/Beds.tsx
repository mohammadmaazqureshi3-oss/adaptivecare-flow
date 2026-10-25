// PAT-02: beds. The Visit pathway reserves them (BedService task) and releases them when a
// transfer fails (undo action ReleaseBed); staff can add beds and free one by hand.

import { useEffect, useState, type FormEvent } from "react";
import { api, type Bed } from "../api";

export function Beds() {
  const [beds, setBeds] = useState<Bed[]>([]);
  const [id, setId] = useState("");
  const [ward, setWard] = useState("W1");
  const [error, setError] = useState<string | null>(null);

  const load = () => api.beds().then(setBeds).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }

  const counts = { free: 0, reserved: 0, occupied: 0 };
  beds.forEach((b) => counts[b.status]++);

  return (
    <div className="card beds">
      <div className="inline">
        <h3 className="flush">Beds</h3>
        <span className="muted small">
          {counts.free} free · {counts.reserved} reserved · {counts.occupied} occupied
        </span>
      </div>
      <form
        className="inline"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          run(async () => {
            await api.addBed(id, ward);
            setId("");
          });
        }}
      >
        <input placeholder="W1-07" value={id} onChange={(e) => setId(e.target.value)} required />
        <input placeholder="Ward" value={ward} onChange={(e) => setWard(e.target.value)} required />
        <button className="ghost">Add bed</button>
      </form>
      {error && <p className="error small">{error}</p>}
      <div className="bed-grid">
        {beds.map((b) => (
          <div key={b.id} className={`bed bed-${b.status}`} title={b.case_id ? `case ${b.case_id}` : undefined}>
            <strong>{b.id}</strong>
            <span className="small">{b.status}</span>
            {b.patient_id && <code className="small">{b.patient_id}</code>}
            {b.status !== "free" && (
              <button className="ghost small" onClick={() => run(() => api.releaseBed(b.id))}>
                Free
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

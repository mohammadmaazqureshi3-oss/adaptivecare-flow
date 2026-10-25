// ENG-06: escalation alerts for my role. A manager is alerted when a task is still open
// after every level of the chain the designer drew. Email/SMS delivery is WRK-03.

import { useEffect, useState } from "react";
import { api, type Notification } from "../api";

export function Alerts() {
  const [items, setItems] = useState<Notification[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      api
        .notifications()
        .then(setItems)
        .catch((e) => setError(e.message));
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="page">
      <h2>Alerts</h2>
      {error && <p className="error">{error}</p>}
      {items === null ? (
        <p className="muted">Loading…</p>
      ) : items.length === 0 ? (
        <p className="muted">No alerts. Overdue tasks that escalate past the last level appear here.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>For</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {items.map((n) => (
              <tr key={n.id}>
                <td className="muted">
                  {new Date(n.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                </td>
                <td>{n.role}</td>
                <td>{n.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ENG-06: escalation alerts for my role. WRK-03: the same alerts by email or SMS to the
// role's alert contacts; managers and admins see what was sent, admins keep the contacts.

import { useEffect, useState, type FormEvent } from "react";
import { api, type AlertContact, type Delivery, type Notification, type User } from "../api";

const ALERT_ROLES = ["charge_nurse", "manager", "nurse", "doctor", "admin"];

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "–";
}

export function Alerts({ user }: { user: User }) {
  const [items, setItems] = useState<Notification[] | null>(null);
  const [sent, setSent] = useState<Delivery[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => {
      api
        .notifications()
        .then(setItems)
        .catch((e) => setError(e.message));
      api
        .deliveries()
        .then(setSent)
        .catch(() => undefined);
    };
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
        <p className="muted">No alerts. Overdue tasks that escalate appear here.</p>
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
                <td className="muted">{when(n.created_at)}</td>
                <td>{n.role}</td>
                <td>{n.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section>
        <h3>Sent by email and SMS</h3>
        {sent.length === 0 ? (
          <p className="muted">Nothing sent yet{user.role === "admin" ? "; add alert contacts below" : ""}.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>To</th>
                <th>Message</th>
                <th>Status</th>
                <th>Sent</th>
              </tr>
            </thead>
            <tbody>
              {sent.map((d) => (
                <tr key={d.id}>
                  <td>
                    {d.channel} · {d.address}
                  </td>
                  <td className="small">{d.text}</td>
                  <td>
                    <span className={`badge badge-delivery-${d.status}`}>{d.status}</span>
                    {d.last_error && (
                      <span className="muted small" title={d.last_error}>
                        {" "}
                        after {d.attempts} attempts
                      </span>
                    )}
                  </td>
                  <td className="muted">{when(d.sent_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {user.role === "admin" && <Contacts />}
    </div>
  );
}

function Contacts() {
  const [contacts, setContacts] = useState<AlertContact[]>([]);
  const [role, setRole] = useState("charge_nurse");
  const [channel, setChannel] = useState<"email" | "sms">("email");
  const [address, setAddress] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reload = () =>
    api
      .alertContacts()
      .then(setContacts)
      .catch((e) => setError(e.message));
  useEffect(() => {
    reload();
  }, []);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.addAlertContact({ role, channel, address, name });
      setAddress("");
      setName("");
      reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section>
      <h3>Alert contacts</h3>
      <p className="muted small">Every alert for a role goes to that role's active contacts.</p>
      <form className="row-form" onSubmit={add}>
        <label>
          Role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {ALERT_ROLES.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label>
          By
          <select value={channel} onChange={(e) => setChannel(e.target.value as "email" | "sms")}>
            <option value="email">email</option>
            <option value="sms">SMS</option>
          </select>
        </label>
        <label className="grow">
          {channel === "email" ? "Email address" : "Phone (+49…)"}
          <input value={address} required onChange={(e) => setAddress(e.target.value)} />
        </label>
        <label className="grow">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <button className="primary" type="submit">
          Add
        </button>
      </form>
      {error && <p className="error">{error}</p>}
      {contacts.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Role</th>
              <th>Contact</th>
              <th>Name</th>
              <th>Active</th>
            </tr>
          </thead>
          <tbody>
            {contacts.map((c) => (
              <tr key={c.id} className={c.active ? "" : "inactive"}>
                <td>{c.role}</td>
                <td>
                  {c.channel} · {c.address}
                </td>
                <td>{c.name}</td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Alerts to ${c.address}`}
                    checked={c.active}
                    onChange={() => api.setAlertContact(c.id, !c.active).then(reload)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

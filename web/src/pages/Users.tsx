import { useEffect, useState, type FormEvent } from "react";
import { api, ROLES, type Role, type User } from "../api";

// AUTH-01: the admin creates users and gives each a role.
export function Users({ me }: { me: User }) {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "nurse" as Role });

  const load = () => api.users().then(setUsers).catch((e) => setError(e.message));
  useEffect(() => {
    load();
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

  function create(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      await api.createUser(form);
      setForm({ name: "", email: "", password: "", role: form.role });
    });
  }

  return (
    <div className="page">
      <h2>Users and roles</h2>
      <form className="card row-form" onSubmit={create}>
        <label className="grow">
          Name
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        </label>
        <label className="grow">
          Email
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            minLength={8}
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
          />
        </label>
        <label>
          Role
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            {ROLES.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <button className="primary">Add user</button>
      </form>
      {error && <p className="error">{error}</p>}
      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className={u.active ? "" : "inactive"}>
              <td>{u.name}</td>
              <td>{u.email}</td>
              <td>
                <select
                  value={u.role}
                  disabled={u.id === me.id}
                  onChange={(e) => run(() => api.updateUser(u.id, { role: e.target.value as Role }))}
                >
                  {ROLES.map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </td>
              <td>{u.active ? "Active" : "Deactivated"}</td>
              <td>
                {u.id !== me.id && (
                  <button
                    className="ghost"
                    onClick={() => {
                      // Deactivating locks the person out (they cannot sign in), so it is confirmed.
                      if (u.active && !window.confirm(`Deactivate ${u.name} (${u.email})? They will no longer be able to sign in.`)) return;
                      run(() => api.updateUser(u.id, { active: !u.active }));
                    }}
                  >
                    {u.active ? "Deactivate" : "Reactivate"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">
        Users are never deleted, only deactivated, so the audit trail keeps who did what. A role change takes
        effect at that user's next token refresh (within 15 minutes).
      </p>
    </div>
  );
}

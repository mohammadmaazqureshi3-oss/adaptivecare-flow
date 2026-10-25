import { useEffect, useState, type FormEvent } from "react";
import { api, type PathwaySummary, type User } from "../api";
import { StatusBadge } from "../editor/StatusBadge";

export function PathwayList({ user, onOpen }: { user: User; onOpen: (id: string) => void }) {
  const [items, setItems] = useState<PathwaySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const canCreate = user.role === "designer";

  useEffect(() => {
    api.pathways().then(setItems).catch((e) => setError(e.message));
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createPathway(id, name);
      onOpen(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the pathway");
    }
  }

  return (
    <div className="page">
      <h2>Pathways</h2>
      {canCreate && (
        <form className="card row-form" onSubmit={create}>
          <label>
            Id
            <input
              value={id}
              onChange={(e) => setId(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))}
              placeholder="triage"
              pattern="[a-z][a-z0-9_]{1,63}"
              required
            />
          </label>
          <label className="grow">
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Emergency triage" required />
          </label>
          <button className="primary">New pathway</button>
        </form>
      )}
      {error && <p className="error">{error}</p>}
      {items === null ? (
        <p className="muted">Loading…</p>
      ) : items.length === 0 ? (
        <p className="muted">No pathways yet{canCreate ? ": create the first one above." : "."}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Id</th>
              <th>Name</th>
              <th>Latest version</th>
              <th>Published</th>
              <th>Last edited by</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id} className="clickable" onClick={() => onOpen(p.id)}>
                <td>
                  <code>{p.id}</code>
                </td>
                <td>{p.name}</td>
                <td>
                  {p.latest_version && (
                    <>
                      v{p.latest_version.number} <StatusBadge status={p.latest_version.status} />
                    </>
                  )}
                </td>
                <td>{p.published_versions.length ? p.published_versions.map((n) => `v${n}`).join(", ") : "—"}</td>
                <td className="muted">{p.latest_version?.author}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

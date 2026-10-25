import { useEffect, useState } from "react";
import { api, setLoggedOutHandler, type User } from "./api";
import { Editor } from "./pages/Editor";
import { Login } from "./pages/Login";
import { PathwayList } from "./pages/PathwayList";
import { Patients } from "./pages/Patients";
import { Users } from "./pages/Users";

// Hash routes keep the app a static bundle: #/pathways, #/pathways/<id>, #/users.
function useHashRoute(): [string[], (path: string) => void] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const onChange = () => setParts(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return [parts, (path) => (window.location.hash = path)];
}

const PATHWAY_ROLES = ["designer", "manager", "admin"];
const CLINICAL_ROLES = ["nurse", "doctor"];

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [route, go] = useHashRoute();

  useEffect(() => {
    setLoggedOutHandler(() => setUser(null));
    api
      .resume()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setChecking(false));
  }, []);

  if (checking) return <div className="centered muted">Loading…</div>;
  if (!user) return <Login onLogin={setUser} />;

  const canSeePathways = PATHWAY_ROLES.includes(user.role);
  const clinical = CLINICAL_ROLES.includes(user.role);
  const [section = canSeePathways ? "pathways" : clinical ? "patients" : "home", id] = route;

  return (
    <div className="app">
      <header className="topbar">
        <strong className="brand">AdaptiveCare Flow</strong>
        <nav>
          {canSeePathways && (
            <a className={section === "pathways" ? "active" : ""} href="#/pathways">
              Pathways
            </a>
          )}
          {clinical && (
            <a className={section === "patients" ? "active" : ""} href="#/patients">
              Patients
            </a>
          )}
          {user.role === "admin" && (
            <a className={section === "users" ? "active" : ""} href="#/users">
              Users
            </a>
          )}
        </nav>
        <span className="spacer" />
        <span className="muted">
          {user.name} · <span className={`role role-${user.role}`}>{user.role}</span>
        </span>
        <button
          className="ghost"
          onClick={() => {
            api.logout();
            setUser(null);
          }}
        >
          Log out
        </button>
      </header>
      <main className="content">
        {section === "pathways" && canSeePathways && !id && <PathwayList user={user} onOpen={(pid) => go(`/pathways/${pid}`)} />}
        {section === "pathways" && canSeePathways && id && <Editor key={id} pathwayId={id} user={user} />}
        {section === "users" && user.role === "admin" && <Users me={user} />}
        {section === "patients" && clinical && <Patients />}
        {section === "home" && (
          <div className="centered">
            <div className="card narrow">
              <h2>Welcome, {user.name}</h2>
              <p className="muted">
                Dashboards for {user.role}s arrive in Sprint 7 (MON-02).
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

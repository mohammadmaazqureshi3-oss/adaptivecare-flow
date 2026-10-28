"""Create demo users and load the example pathways through the gateway (development only).

Usage: .venv/bin/python scripts/seed_demo.py [gateway-url]
The admin account comes from ADMIN_EMAIL / ADMIN_PASSWORD in .env.example.
Demo passwords below are development fixtures, never real credentials.
"""

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
DEMO_USERS = [
    ("Dana Designer", "designer@adaptivecare.test", "designer-demo-1", "designer"),
    ("Nadia Nurse", "nurse@adaptivecare.test", "nurse-demo-1", "nurse"),
    ("Dev Doctor", "doctor@adaptivecare.test", "doctor-demo-1", "doctor"),
    ("Mia Manager", "manager@adaptivecare.test", "manager-demo-1", "manager"),
    ("Cara Charge", "charge@adaptivecare.test", "charge-demo-1", "charge_nurse"),
]
# Patients are not seeded: registering one starts a real Triage case (register them in the app).
CLINICAL = [
    ("triage", "Emergency triage"),
    ("assessment", "Assessment"),
    ("visit", "Ward visit and admission"),
]
BEDS = [(f"W1-{i:02d}", "W1") for i in range(1, 7)] + [(f"W2-{i:02d}", "W2") for i in range(1, 5)]


def env(name: str) -> str:
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line.startswith(f"{name}="):
            return os.environ.get(name, line.split("=", 1)[1])
    raise SystemExit(f"{name} missing from .env.example")


def token(c: httpx.Client, email: str, password: str) -> dict[str, str]:
    r = c.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def reactivate_demo_users(c: httpx.Client, admin: dict[str, str]) -> None:
    """A demo account deactivated on the Users page cannot sign in; the seed turns it back on."""
    demo = {email for _, email, _, _ in DEMO_USERS}
    for user in c.get("/users", headers=admin).json():
        if user["email"] in demo and not user["active"]:
            c.patch(f"/users/{user['id']}", json={"active": True}, headers=admin).raise_for_status()
            print(f"user {user['email']:32} reactivated")


def install_deadlock_example(c: httpx.Client, designer: dict[str, str]) -> None:
    """The Verifier's worked example as an unfixed draft, so the demo can be repeated after someone
    fixed and published it in an earlier run (a published version is never changed: a new draft)."""
    model = json.loads((ROOT / "pathways" / "imaging_deadlock.json").read_text())
    c.post("/pathways", json={"id": "imaging_deadlock", "name": "Imaging (has a deadlock)"}, headers=designer)
    latest = c.get("/pathways/imaging_deadlock/versions", headers=designer).json()[-1]
    current = c.get(f"/versions/{latest['id']}", headers=designer).json()["model"]
    if latest["status"] == "draft" and current.get("nodes") == model["nodes"]:
        print(f"pathway imaging_deadlock: v{latest['number']} is the deadlock draft")
        return
    if latest["status"] not in ("draft", "verified"):
        latest = c.post("/pathways/imaging_deadlock/versions", headers=designer).json()
    c.put(f"/versions/{latest['id']}", json={"model": model}, headers=designer).raise_for_status()
    print(
        f"pathway imaging_deadlock: v{latest['number']} reset to the deadlock draft (the Verifier's example)"
    )


def install_clinical(c: httpx.Client, designer: dict[str, str], admin: dict[str, str]) -> None:
    """CLN-01..03 the way a team would: a new version of each pathway, verified, published,
    deployed; older running versions are undeployed (drained) once the new one runs."""
    for pid, title in CLINICAL:
        model = json.loads((ROOT / "pathways" / "clinical" / f"{pid}.json").read_text())
        if c.post("/pathways", json={"id": pid, "name": title}, headers=designer).status_code == 201:
            print(f"pathway {pid}: created")
        versions = c.get(f"/pathways/{pid}/versions", headers=designer).json()
        latest = versions[-1]
        if latest["status"] != "draft" and latest["status"] != "verified":
            current = c.get(f"/versions/{latest['id']}", headers=designer).json()["model"]
            if current.get("nodes") == model["nodes"] and current.get("edges") == model["edges"]:
                state = f"v{latest['number']} already holds the clinical model ({latest['status']})"
                print(f"pathway {pid}: {state}")
                _deploy(c, admin, pid, latest)
                continue
            latest = c.post(f"/pathways/{pid}/versions", headers=designer).json()
        c.put(f"/versions/{latest['id']}", json={"model": model}, headers=designer).raise_for_status()
        report = c.post(f"/versions/{latest['id']}/verify", headers=designer).json()["report"]
        if report["status"] != "SAFE":
            print(f"pathway {pid}: Verify says {report['status']}; not published")
            continue
        c.post(f"/versions/{latest['id']}/publish", headers=designer).raise_for_status()
        print(f"pathway {pid}: v{latest['number']} verified SAFE and published")
        _deploy(c, admin, pid, latest)


def _deploy(c: httpx.Client, admin: dict[str, str], pid: str, version: dict) -> None:  # type: ignore[type-arg]
    r = c.post(f"/versions/{version['id']}/deploy", headers=admin, timeout=60).json()
    print(f"pathway {pid}: v{version['number']} {r.get('status', r.get('detail'))}")
    for d in c.get("/deployments", params={"pathway": pid}, headers=admin).json():
        if d["status"] == "running" and d["version_id"] != version["id"]:
            undeployed = c.delete(f"/deployments/{d['id']}", headers=admin).json()
            print(f"pathway {pid}: v{d['version']} undeployed ({undeployed['status']})")


def main() -> None:
    with httpx.Client(base_url=GATEWAY, timeout=30) as c:
        admin = token(c, env("ADMIN_EMAIL"), env("ADMIN_PASSWORD"))
        for name, email, password, role in DEMO_USERS:
            r = c.post(
                "/users",
                json={"name": name, "email": email, "password": password, "role": role},
                headers=admin,
            )
            print(f"user {email:32} {role:9} {'created' if r.status_code == 201 else r.json()['detail']}")
        reactivate_demo_users(c, admin)
        designer = token(c, DEMO_USERS[0][1], DEMO_USERS[0][2])
        install_deadlock_example(c, designer)
        install_clinical(c, designer, admin)
        nurse = token(c, DEMO_USERS[1][1], DEMO_USERS[1][2])
        added = sum(
            c.post("/beds", json={"id": b, "ward": w}, headers=nurse).status_code == 201 for b, w in BEDS
        )
        print(f"beds: {added} added")


if __name__ == "__main__":
    main()

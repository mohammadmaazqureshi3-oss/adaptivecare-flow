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
PATHWAYS = [("triage", "Emergency triage"), ("imaging_deadlock", "Imaging (has a deadlock)")]
# Synthetic patients only (NFR-EXT-01).
PATIENTS = [
    ("Ada Lovelace", "1985-12-10", "female", "walk_in", "chest pain"),
    ("Alan Turing", "1952-06-23", "male", "ambulance", "shortness of breath"),
    ("Grace Hopper", "1946-12-09", "female", "referral", "fall, wrist pain"),
]


def env(name: str) -> str:
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line.startswith(f"{name}="):
            return os.environ.get(name, line.split("=", 1)[1])
    raise SystemExit(f"{name} missing from .env.example")


def token(c: httpx.Client, email: str, password: str) -> dict[str, str]:
    r = c.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def publish_triage(c: httpx.Client, designer: dict[str, str]) -> None:
    """Verify and publish Triage if its latest version is a draft, so an engine can run it."""
    latest = c.get("/pathways/triage/versions", headers=designer).json()[-1]
    if latest["status"] == "published":
        print(f"pathway triage: v{latest['number']} already published")
        return
    report = c.post(f"/versions/{latest['id']}/verify", headers=designer).json()["report"]
    if report["status"] != "SAFE":
        print(f"pathway triage: not published, Verify says {report['status']}")
        return
    c.post(f"/versions/{latest['id']}/publish", headers=designer).raise_for_status()
    print(f"pathway triage: v{latest['number']} verified SAFE and published")


def deploy_triage(c: httpx.Client, admin: dict[str, str]) -> None:
    """Deploy the latest published Triage version (DEP-01), so registrations start cases."""
    for v in reversed(c.get("/pathways/triage/versions", headers=admin).json()):
        if v["status"] in ("published", "deployed"):
            r = c.post(f"/versions/{v['id']}/deploy", headers=admin, timeout=60)
            print(f"pathway triage: v{v['number']} {r.json().get('status', r.json().get('detail'))}")
            return


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
        designer = token(c, DEMO_USERS[0][1], DEMO_USERS[0][2])
        for pid, title in PATHWAYS:
            r = c.post("/pathways", json={"id": pid, "name": title}, headers=designer)
            if r.status_code != 201:
                print(f"pathway {pid}: {r.json()['detail']}")
                continue
            vid = r.json()["latest_version"]["id"]
            model = json.loads((ROOT / "pathways" / f"{pid}.json").read_text())
            c.put(f"/versions/{vid}", json={"model": model}, headers=designer).raise_for_status()
            print(f"pathway {pid}: loaded as draft v1")
        publish_triage(c, designer)
        deploy_triage(c, admin)
        nurse = token(c, DEMO_USERS[1][1], DEMO_USERS[1][2])
        for name, dob, sex, mode, complaint in PATIENTS:
            body = {
                "name": name,
                "date_of_birth": dob,
                "sex": sex,
                "arrival_mode": mode,
                "chief_complaint": complaint,
            }
            r = c.post("/patients", json=body, headers=nurse)
            print(f"patient {name:14} {r.json()['mrn'] if r.status_code == 201 else 'already registered'}")


if __name__ == "__main__":
    main()

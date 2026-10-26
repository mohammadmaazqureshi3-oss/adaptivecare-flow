"""Stress test through the gateway (plan Section 14: "the NFR-PERF targets, then load until
the system fails"). Development only: it uses the demo nurse account from seed_demo.py.

    .venv/bin/python scripts/load_test.py [gateway-url] [seconds-per-step]

Read-only traffic, like nurses refreshing their worklist (80%) and searching patients (20%),
at rising rates. Each step reports throughput, p50/p95 latency and errors; the run stops at
the first step where more than 5% of requests fail or p95 exceeds 2 seconds.
"""

from __future__ import annotations

import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

GATEWAY = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
STEP_S = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
RATES = (10, 25, 50, 100, 200, 400, 800)
NURSE = ("nurse@adaptivecare.test", "nurse-demo-1")  # development fixture, see seed_demo.py
MAX_ERROR_RATE = 0.05
MAX_P95_S = 2.0


def login(c: httpx.Client) -> dict[str, str]:
    r = c.post("/auth/login", json={"email": NURSE[0], "password": NURSE[1]})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def step(c: httpx.Client, headers: dict[str, str], rate: int) -> dict[str, float]:
    """Send ``rate`` requests per second for STEP_S seconds (open loop: arrivals do not wait)."""
    latencies: list[float] = []
    errors = 0
    lock = threading.Lock()

    def one(i: int) -> None:
        nonlocal errors
        path = "/tasks" if i % 5 else "/patients?q=a"
        t0 = time.perf_counter()
        try:
            ok = c.get(path, headers=headers).status_code == 200
        except httpx.HTTPError:
            ok = False
        with lock:
            latencies.append(time.perf_counter() - t0)
            errors += not ok

    total = int(rate * STEP_S)
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(256, rate)) as pool:
        for i in range(total):
            time.sleep(max(0.0, start + i / rate - time.monotonic()))
            pool.submit(one, i)
    elapsed = time.monotonic() - start
    latencies.sort()
    return {
        "rate": rate,
        "achieved": total / elapsed,
        "p50_ms": statistics.median(latencies) * 1000,
        "p95_ms": latencies[int(0.95 * len(latencies))] * 1000,
        "error_rate": errors / total,
    }


def main() -> None:
    limits = httpx.Limits(max_connections=256, max_keepalive_connections=256)
    with httpx.Client(base_url=GATEWAY, timeout=10, limits=limits) as c:
        headers = login(c)
        print(f"{'target/s':>9} {'achieved/s':>11} {'p50 ms':>8} {'p95 ms':>8} {'errors':>7}")
        for rate in RATES:
            r = step(c, headers, rate)
            ms = f"{r['p50_ms']:>8.0f} {r['p95_ms']:>8.0f}"
            print(f"{rate:>9} {r['achieved']:>11.0f} {ms} {r['error_rate']:>7.1%}")
            if r["error_rate"] > MAX_ERROR_RATE or r["p95_ms"] > MAX_P95_S * 1000:
                print(f"saturated at {rate} requests per second")
                return
        print("not saturated at the highest step")


if __name__ == "__main__":
    main()

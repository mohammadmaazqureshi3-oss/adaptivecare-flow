"""Charts for the report, computed from the repository itself (never drawn by hand).

    python scripts/report_charts.py        # needs matplotlib (e.g. pip install matplotlib)

Writes docs/report/figures/{velocity,growth,nfr}.png:
- velocity: story points delivered per increment (the backlog points of the stories each
  tag completed; plan Section 12);
- growth: Python test functions and non-test code lines at each sprint tag (git);
- nfr: measured performance against the NFR targets (docs/measurements/nfr-results.md).
"""

from __future__ import annotations

import subprocess  # nosec B404 - runs fixed developer tools (pandoc, git)
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "report" / "figures"
TAGS = [f"sprint-{i}" for i in range(8)]
# Points per sprint from the product backlog (plan Section 12); Sprint 0 had no stories.
POINTS = {"sprint-0": 0, "sprint-1": 30, "sprint-2": 33, "sprint-3": 33, "sprint-4": 31,
          "sprint-5": 30, "sprint-6": 30, "sprint-7": 20}  # fmt: skip
INK, ACCENT, MUTED = "#1f2933", "#2563eb", "#9aa5b1"


def git(*args: str) -> str:
    # Read-only git commands with fixed arguments, run by the developer.
    cmd = ["git", *args]
    return subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True).stdout  # noqa: S603  # nosec B603 B607


def tests_at(tag: str) -> int:
    out = git("grep", "-h", "-E", r"^[[:space:]]*def test_", tag, "--", "*.py")
    return len(out.splitlines())


def code_lines_at(tag: str) -> int:
    files = [f for f in git("ls-tree", "-r", "--name-only", tag).splitlines()
             if f.endswith((".py", ".ts", ".tsx")) and "test" not in f]  # fmt: skip
    return sum(len(git("show", f"{tag}:{f}").splitlines()) for f in files)


def style(ax: plt.Axes) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=INK)
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    ax.set_axisbelow(True)


def velocity() -> None:
    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=200)
    labels = [t.replace("sprint-", "S") for t in TAGS]
    bars = ax.bar(labels, [POINTS[t] for t in TAGS], color=ACCENT, width=0.6)
    ax.bar_label(bars, padding=2, fontsize=8, color=INK)
    ax.set_ylabel("Story points delivered", color=INK)
    ax.set_title("Velocity per increment (planned = delivered, 207 points)", fontsize=10, color=INK)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "velocity.png")


def growth() -> None:
    tests = [tests_at(t) for t in TAGS]
    lines = [code_lines_at(t) for t in TAGS]
    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=200)
    labels = [t.replace("sprint-", "S") for t in TAGS]
    ax.plot(labels, tests, marker="o", color=ACCENT, label="Python test functions")
    ax.set_ylabel("Test functions", color=ACCENT)
    style(ax)
    ax2 = ax.twinx()
    ax2.plot(labels, lines, marker="s", color=MUTED, label="Code lines (excluding tests)")
    ax2.set_ylabel("Code lines", color=MUTED)
    ax2.spines["top"].set_visible(False)
    for x, y in zip(labels, tests, strict=True):
        ax.annotate(str(y), (x, y), textcoords="offset points", xytext=(0, -13), ha="center", fontsize=7)
    ax.set_title("Tests and code at each sprint tag (from git)", fontsize=10, color=INK)
    fig.legend(loc="upper left", bbox_to_anchor=(0.1, 0.88), fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "growth.png")


def nfr() -> None:
    # (label, measured, limit, unit) from docs/measurements/nfr-results.md
    rows = [
        ("NFR-PERF-01 Verifier", 0.04, 2.0, "s"),
        ("NFR-PERF-02 Engine p95", 0.003, 0.2, "s"),
        ("NFR-PERF-03 Simulator", 5.0, 60.0, "s"),
        ("NFR-PERF-04 ML p95", 0.011, 0.1, "s"),
    ]
    fig, ax = plt.subplots(figsize=(7, 2.8), dpi=200)
    names = [r[0] for r in rows]
    share = [r[1] / r[2] * 100 for r in rows]
    bars = ax.barh(names, share, color=ACCENT, height=0.5)
    ax.axvline(100, color="#b91c1c", linewidth=1.2)
    ax.text(99, 3.35, "target ", color="#b91c1c", fontsize=8, ha="right")
    ax.bar_label(bars, labels=[f"{r[1]:g} {r[3]} of {r[2]:g} {r[3]}" for r in rows], padding=4, fontsize=8)
    ax.set_xlim(0, 115)
    ax.set_xlabel("Measured as % of the target (lower is better)", color=INK)
    ax.set_title("Performance NFRs: measured against target", fontsize=10, color=INK)
    ax.invert_yaxis()
    style(ax)
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.8)
    fig.tight_layout()
    fig.savefig(OUT / "nfr.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    velocity()
    growth()
    nfr()
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.png"))))


if __name__ == "__main__":
    main()

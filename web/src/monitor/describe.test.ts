import { describe as suite, expect, it } from "vitest";
import type { CaseEvent } from "../api";
import { describe, minutes, tone } from "./describe";

const ev = (type: string, detail: Record<string, unknown> = {}): CaseEvent => ({
  id: 1,
  type,
  token_id: "",
  at: "2026-10-26T08:00:00+00:00",
  detail,
});

suite("MON-01 case history lines", () => {
  it("names who did what", () => {
    expect(describe(ev("TaskRequested", { label: "Measure vital signs", role: "nurse" }))).toBe(
      "Measure vital signs requested from nurse",
    );
    expect(describe(ev("TaskRequested", { node: "news2", service: "News2Score" }))).toBe(
      "news2 requested from News2Score",
    );
    expect(describe(ev("TaskCompleted", { completed_by: "nadia@x.org", outputs: { spo2: 86, mental: "alert" } }))).toBe(
      'Completed by nadia@x.org: spo2 = 86, mental = "alert"',
    );
  });

  it("shows an override with its reason and marks it", () => {
    const e = ev("TaskCompleted", { outputs: { confirmed_urgency: 1 }, override: { suggested: 2, decided: 1, reason: "grey" } });
    expect(describe(e)).toBe("Completed: confirmed_urgency = 1 · changed 2 → 1: “grey”");
    expect(tone(e)).toBe("warn");
  });

  it("explains failures and escalations", () => {
    expect(describe(ev("TaskFailed", { reason: "no free bed", temporary: true }))).toBe(
      "Failed (temporary, will retry): no free bed",
    );
    expect(tone(ev("TaskFailed"))).toBe("bad");
    expect(describe(ev("TaskReassigned", { role: "charge_nurse", level: 1 }))).toBe(
      "Overdue: escalated to charge_nurse (level 1)",
    );
    expect(tone(ev("Compensated", { ok: false }))).toBe("bad");
    expect(describe(ev("TriageCompleted"))).toBe("TriageCompleted announced");
  });

  it("formats minutes", () => {
    expect(minutes(4.25)).toBe("4.3 min");
    expect(minutes(45)).toBe("45 min");
    expect(minutes(90)).toBe("1.5 h");
    expect(minutes(null)).toBe("–");
  });
});

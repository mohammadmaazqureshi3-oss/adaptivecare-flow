// MON-01: one readable line per recorded case event, for the case history timeline.

import type { CaseEvent } from "../api";

type Detail = Record<string, unknown>;

function str(v: unknown): string {
  return v === undefined || v === null ? "" : String(v);
}

function values(outputs: unknown): string {
  if (!outputs || typeof outputs !== "object") return "";
  return Object.entries(outputs as Detail)
    .map(([k, v]) => `${k} = ${typeof v === "string" ? `"${v}"` : str(v)}`)
    .join(", ");
}

const LINES: Record<string, (d: Detail) => string> = {
  CaseStarted: (d) => `Case started by ${str(d.trigger) || "its trigger"}`,
  TaskRequested: (d) =>
    `${str(d.label) || str(d.node)} requested from ${str(d.role) || str(d.service) || "a service"}`,
  TaskCompleted: (d) => {
    const by = d.completed_by ? ` by ${str(d.completed_by)}` : "";
    const out = values(d.outputs);
    const o = d.override as Detail | undefined;
    const changed = o ? ` · changed ${str(o.suggested)} → ${str(o.decided)}: “${str(o.reason)}”` : "";
    return `Completed${by}${out ? `: ${out}` : ""}${changed}`;
  },
  TaskFailed: (d) => `Failed (${d.temporary ? "temporary, will retry" : "permanent"}): ${str(d.reason)}`,
  TaskReassigned: (d) => `Overdue: escalated to ${str(d.role)} (level ${str(d.level)})`,
  NotificationRequested: (d) => `Alert to ${str(d.role)}: ${str(d.message)}`,
  CancelRequested: (d) => `Cancelled ${str(d.node)}`,
  CompensateRequested: (d) => `Undo requested: ${str(d.label) || str(d.action) || str(d.node)}`,
  Compensated: (d) => (d.ok === false ? `Undo failed: ${str(d.reason)}` : "Undo done"),
  CaseCompleted: (d) => `Case completed at ${str(d.end)}`,
  CaseFailed: (d) => `Case failed: ${str(d.reason)}`,
  CaseCompensated: (d) => `Case undone: ${str(d.reason)}`,
  CaseCancelled: () => "Case cancelled",
};

export function describe(e: CaseEvent): string {
  const line = LINES[e.type];
  return line ? line(e.detail) : `${e.type} announced`;
}

// Severity for the timeline marker colour.
export function tone(e: CaseEvent): "ok" | "bad" | "warn" | "plain" {
  if (["TaskFailed", "CaseFailed", "CaseCompensated"].includes(e.type)) return "bad";
  if (e.type === "Compensated" && e.detail.ok === false) return "bad";
  if (["TaskReassigned", "NotificationRequested", "CompensateRequested"].includes(e.type)) return "warn";
  if (e.type === "TaskCompleted" && e.detail.override) return "warn";
  if (["CaseCompleted", "TaskCompleted"].includes(e.type)) return "ok";
  return "plain";
}

export function minutes(m: number | null | undefined): string {
  if (m === null || m === undefined) return "–";
  return m < 60 ? `${m.toFixed(m < 10 ? 1 : 0)} min` : `${(m / 60).toFixed(1)} h`;
}

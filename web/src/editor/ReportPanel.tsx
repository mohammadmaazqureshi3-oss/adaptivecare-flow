// The Verifier's report. Selecting an error highlights its nodes and its counterexample
// path on the canvas; step-by-step replay of the path is Sprint 2 work (NFR-USE-01).

import type { Report, VerificationError } from "../api";
import { StatusBadge } from "./StatusBadge";

const TITLES: Record<string, string> = {
  structure: "Structure",
  deadlock: "Deadlock",
  cannot_finish: "Cannot finish",
  unfinished_case: "Unfinished case",
  dead_step: "Dead step",
  duplicate_work: "Duplicate work",
  missing_data: "Missing data",
  type_error: "Type error",
  syntax_error: "Syntax error",
};

export function ReportPanel({
  report,
  selected,
  onSelect,
}: {
  report: Report;
  selected: VerificationError | null;
  onSelect: (e: VerificationError | null) => void;
}) {
  return (
    <div className="report">
      <div className="report-head">
        <StatusBadge status={report.status} />
        <span className="muted small">
          {report.states_explored.toLocaleString()} states · {report.elapsed_ms} ms
          {!report.search_complete && " · search stopped at the state limit"}
        </span>
      </div>
      {report.status === "SAFE" && <p className="small">Sound: every case can finish, cleanly, with its data.</p>}
      <ul className="errors">
        {report.errors.map((e, i) => (
          <li
            key={i}
            className={selected === e ? "selected" : ""}
            onClick={() => onSelect(selected === e ? null : e)}
          >
            <div>
              <strong>{TITLES[e.type] ?? e.type}</strong> <span className="muted small">({e.property})</span>
            </div>
            <div className="small">{e.message}</div>
            {e.path.length > 0 && (
              <div className="small path">
                Path: Start → {e.path.map((m) => m.node).join(" → ")}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

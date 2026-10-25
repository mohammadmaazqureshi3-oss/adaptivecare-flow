// The Verifier's report. Selecting an error highlights it on the canvas; for errors with a
// counterexample, the controls replay the path move by move (NFR-USE-01): ● marks the
// tokens on each arrow and the node that just fired is outlined in blue.

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
  settings: "Task settings",
};

export interface ReplayControls {
  step: number;
  total: number;
  firing: string | null;
  playing: boolean;
  setStep: (step: number) => void;
  setPlaying: (playing: boolean) => void;
}

function Replay({ r, error }: { r: ReplayControls; error: VerificationError }) {
  const last = r.total - 1;
  const caption =
    r.step === 0
      ? "Start: one token waits after Start."
      : r.step === last
        ? `${r.firing} fires. ${error.message}`
        : `Move ${r.step}: ${r.firing} fires.`;
  return (
    <div className="replay" onClick={(e) => e.stopPropagation()}>
      <div className="replay-buttons">
        <button className="ghost" title="First move" disabled={r.step === 0} onClick={() => r.setStep(0)}>
          ⏮
        </button>
        <button className="ghost" title="Previous move" disabled={r.step === 0} onClick={() => r.setStep(r.step - 1)}>
          ◀
        </button>
        <button
          className="ghost"
          title={r.playing ? "Pause" : "Play from here"}
          onClick={() => {
            if (!r.playing && r.step === last) r.setStep(0);
            r.setPlaying(!r.playing);
          }}
        >
          {r.playing ? "⏸" : "▶︎"}
        </button>
        <button className="ghost" title="Next move" disabled={r.step === last} onClick={() => r.setStep(r.step + 1)}>
          ▶
        </button>
        <button className="ghost" title="Last move" disabled={r.step === last} onClick={() => r.setStep(last)}>
          ⏭
        </button>
        <span className="muted small">
          {r.step} / {last}
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={last}
        value={r.step}
        aria-label="Replay position"
        onChange={(e) => r.setStep(Number(e.target.value))}
      />
      <div className="small">{caption}</div>
    </div>
  );
}

export function ReportPanel({
  report,
  selected,
  onSelect,
  replay,
  stale,
}: {
  report: Report;
  selected: VerificationError | null;
  onSelect: (e: VerificationError | null) => void;
  replay: ReplayControls | null;
  stale: boolean;
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
      {stale && <p className="small warn-text">The pathway changed since this report. Verify again.</p>}
      {report.status === "SAFE" && <p className="small">Sound: every case can finish, cleanly, with its data.</p>}
      <ul className="errors">
        {report.errors.map((e, i) => (
          <li key={i} className={selected === e ? "selected" : ""} onClick={() => onSelect(selected === e ? null : e)}>
            <div>
              <strong>{TITLES[e.type] ?? e.type}</strong> <span className="muted small">({e.property})</span>
            </div>
            <div className="small">{e.message}</div>
            {e.path.length > 0 && (
              <div className="small path">Path: Start → {e.path.map((m) => m.node).join(" → ")}</div>
            )}
            {selected === e && replay && <Replay r={replay} error={e} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

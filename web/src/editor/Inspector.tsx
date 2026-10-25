// The properties panel: everything a designer can set on the selected node or arrow
// (plan Section 5, DES-02 inputs/outputs, DES-04 deadlines, escalation, retries, fallback, undo).

import type { ReactNode } from "react";
import { ConditionInput } from "./ConditionInput";
import {
  NODE_LABELS,
  type Duration,
  type EdgeData,
  type Escalation,
  type FlowEdge,
  type FlowNode,
  type NodeData,
  type Variable,
} from "./model";

interface NodeProps {
  node: FlowNode;
  nodes: FlowNode[];
  variables: Variable[];
  readOnly: boolean;
  onChange: (patch: Partial<NodeData>) => void;
  onDelete: () => void;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function num(v: string): number | undefined {
  return v === "" ? undefined : Number(v);
}

function VarPicker({
  label,
  selected,
  variables,
  disabled,
  onChange,
}: {
  label: string;
  selected: string[];
  variables: Variable[];
  disabled: boolean;
  onChange: (v: string[]) => void;
}) {
  return (
    <fieldset className="varpick">
      <legend>{label}</legend>
      {variables.length === 0 && <span className="muted small">Declare variables first.</span>}
      {variables.map((v) => (
        <label key={v.name} className="check">
          <input
            type="checkbox"
            disabled={disabled}
            checked={selected.includes(v.name)}
            onChange={(e) =>
              onChange(e.target.checked ? [...selected, v.name] : selected.filter((s) => s !== v.name))
            }
          />
          {v.name} <span className="muted small">{v.type}</span>
        </label>
      ))}
    </fieldset>
  );
}

export function NodeInspector({ node, nodes, variables, readOnly, onChange, onDelete }: NodeProps) {
  const d = node.data;
  const type = node.type!;
  return (
    <div className="inspector">
      <h3>
        {NODE_LABELS[type]} <code className="muted small">{node.id}</code>
      </h3>
      <Field label="Label">
        <input value={d.label ?? ""} disabled={readOnly} onChange={(e) => onChange({ label: e.target.value })} />
      </Field>

      {type === "start" && (
        <>
          <Field label="Trigger event">
            <input
              value={d.trigger ?? ""}
              disabled={readOnly}
              placeholder="PatientRegistered"
              onChange={(e) => onChange({ trigger: e.target.value })}
            />
          </Field>
          <VarPicker
            label="Input variables (arrive with the trigger)"
            selected={d.inputs ?? []}
            variables={variables}
            disabled={readOnly}
            onChange={(inputs) => onChange({ inputs })}
          />
        </>
      )}

      {type === "timer" && (
        <Field label="Wait (minutes)">
          <input
            type="number"
            min={0}
            value={d.minutes ?? ""}
            disabled={readOnly}
            onChange={(e) => onChange({ minutes: num(e.target.value) })}
          />
        </Field>
      )}

      {type === "task" && <TaskFields node={node} nodes={nodes} variables={variables} readOnly={readOnly} onChange={onChange} />}

      {!readOnly && (
        <button className="danger" onClick={onDelete}>
          Delete {NODE_LABELS[type].toLowerCase()}
        </button>
      )}
    </div>
  );
}

function TaskFields({ node, nodes, variables, readOnly, onChange }: Omit<NodeProps, "onDelete">) {
  const d = node.data;
  const kind = d.kind ?? "human";
  const escalation = d.deadline?.escalation ?? [];
  const setEscalation = (list: Escalation[]) =>
    onChange({ deadline: { minutes: d.deadline?.minutes ?? 10, escalation: list } });

  return (
    <>
      <Field label="Kind">
        <select
          value={kind}
          disabled={readOnly}
          onChange={(e) => onChange({ kind: e.target.value as NodeData["kind"] })}
        >
          <option value="human">Human (worklist)</option>
          <option value="service">Service</option>
          <option value="ml">ML model</option>
        </select>
      </Field>
      {kind === "human" ? (
        <Field label="Role">
          <input value={d.role ?? ""} disabled={readOnly} placeholder="nurse" onChange={(e) => onChange({ role: e.target.value })} />
        </Field>
      ) : (
        <Field label="Service">
          <input
            value={d.service ?? ""}
            disabled={readOnly}
            placeholder={kind === "ml" ? "PredictUrgency" : "BedService"}
            onChange={(e) => onChange({ service: e.target.value })}
          />
        </Field>
      )}
      <VarPicker label="Reads (inputs)" selected={d.inputs ?? []} variables={variables} disabled={readOnly} onChange={(inputs) => onChange({ inputs })} />
      <VarPicker label="Writes (outputs)" selected={d.outputs ?? []} variables={variables} disabled={readOnly} onChange={(outputs) => onChange({ outputs })} />

      <details open={!!d.deadline}>
        <summary>Deadline and escalation</summary>
        <label className="check">
          <input
            type="checkbox"
            disabled={readOnly}
            checked={!!d.deadline}
            onChange={(e) => onChange({ deadline: e.target.checked ? { minutes: 10, escalation: [] } : undefined })}
          />
          Has a deadline
        </label>
        {d.deadline && (
          <>
            <Field label="Deadline (minutes)">
              <input
                type="number"
                min={1}
                value={d.deadline.minutes}
                disabled={readOnly}
                onChange={(e) => onChange({ deadline: { ...d.deadline!, minutes: Number(e.target.value) } })}
              />
            </Field>
            {escalation.map((step, i) => (
              <div className="inline" key={i}>
                <span className="muted small">{i + 1}.</span>
                <input
                  value={step.role}
                  disabled={readOnly}
                  placeholder="charge_nurse"
                  onChange={(e) => setEscalation(escalation.map((s, j) => (j === i ? { ...s, role: e.target.value } : s)))}
                />
                <span className="muted small">after</span>
                <input
                  type="number"
                  className="short"
                  value={step.afterMin}
                  disabled={readOnly}
                  onChange={(e) =>
                    setEscalation(escalation.map((s, j) => (j === i ? { ...s, afterMin: Number(e.target.value) } : s)))
                  }
                />
                <span className="muted small">min</span>
                {!readOnly && (
                  <button className="ghost" onClick={() => setEscalation(escalation.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                )}
              </div>
            ))}
            {!readOnly && (
              <button className="ghost" onClick={() => setEscalation([...escalation, { role: "", afterMin: 5 }])}>
                + escalation level
              </button>
            )}
          </>
        )}
      </details>

      <details open={!!d.retry || !!d.fallback}>
        <summary>Failure handling</summary>
        {kind !== "human" && (
        <Field label="Retries (max)">
          <input
            type="number"
            min={0}
            value={d.retry?.max ?? ""}
            disabled={readOnly}
            onChange={(e) => {
              const max = num(e.target.value);
              onChange({ retry: max ? { max, baseDelayS: d.retry?.baseDelayS ?? 1 } : undefined });
            }}
          />
        </Field>
        )}
        {kind !== "human" && d.retry && (
          <Field label="First retry delay (s), doubling">
            <input
              type="number"
              min={0}
              value={d.retry.baseDelayS}
              disabled={readOnly}
              onChange={(e) => onChange({ retry: { ...d.retry!, baseDelayS: Number(e.target.value) } })}
            />
          </Field>
        )}
        <Field label="Fallback step (if it fails for good)">
          <select value={d.fallback ?? ""} disabled={readOnly} onChange={(e) => onChange({ fallback: e.target.value || undefined })}>
            <option value="">— none: undo finished steps —</option>
            {nodes
              .filter((n) => n.id !== node.id && n.type !== "start")
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.data.label || n.id} ({n.id})
                </option>
              ))}
          </select>
        </Field>
        <Field label="Undo action (compensation)">
          <input value={d.undo ?? ""} disabled={readOnly} placeholder="ReleaseBed" onChange={(e) => onChange({ undo: e.target.value })} />
        </Field>
      </details>

      <details open={!!d.duration}>
        <summary>Duration (for simulation)</summary>
        <DurationFields value={d.duration} disabled={readOnly} onChange={(duration) => onChange({ duration })} />
      </details>
    </>
  );
}

const DIST_FIELDS: Record<Duration["dist"], (keyof Duration)[]> = {
  fixed: ["meanMin"],
  exponential: ["meanMin"],
  lognormal: ["meanMin", "sdMin"],
  triangular: ["minMin", "modeMin", "maxMin"],
};
const FIELD_LABEL: Record<string, string> = {
  meanMin: "mean",
  sdMin: "sd",
  minMin: "min",
  modeMin: "mode",
  maxMin: "max",
};

function DurationFields({
  value,
  disabled,
  onChange,
}: {
  value: Duration | undefined;
  disabled: boolean;
  onChange: (d: Duration | undefined) => void;
}) {
  return (
    <>
      <Field label="Distribution">
        <select
          value={value?.dist ?? ""}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value ? { dist: e.target.value as Duration["dist"] } : undefined)}
        >
          <option value="">— not set —</option>
          <option value="fixed">fixed</option>
          <option value="exponential">exponential</option>
          <option value="lognormal">lognormal</option>
          <option value="triangular">triangular</option>
        </select>
      </Field>
      {value && (
        <div className="inline">
          {DIST_FIELDS[value.dist].map((k) => (
            <label key={k} className="mini">
              <span className="muted small">{FIELD_LABEL[k]} (min)</span>
              <input
                type="number"
                min={0}
                step="0.1"
                className="short"
                disabled={disabled}
                value={(value[k] as number | undefined) ?? ""}
                onChange={(e) => onChange({ ...value, [k]: num(e.target.value) })}
              />
            </label>
          ))}
        </div>
      )}
    </>
  );
}

export function EdgeInspector({
  edge,
  sourceType,
  variables,
  readOnly,
  onChange,
  onMakeDefault,
  onDelete,
}: {
  edge: FlowEdge;
  sourceType: string | undefined;
  variables: Variable[];
  readOnly: boolean;
  onChange: (patch: Partial<EdgeData>) => void;
  onMakeDefault: () => void;
  onDelete: () => void;
}) {
  const d = edge.data ?? {};
  return (
    <div className="inspector">
      <h3>
        Arrow <code className="muted small">{edge.source} → {edge.target}</code>
      </h3>
      {sourceType === "xor_split" ? (
        <>
          <label className="check">
            <input type="radio" disabled={readOnly} checked={!!d.default} onChange={onMakeDefault} />
            Default branch (taken when no condition is true)
          </label>
          {!d.default && (
            <Field label="Condition">
              <ConditionInput
                value={d.condition ?? ""}
                variables={variables}
                disabled={readOnly}
                onChange={(condition) => onChange({ condition })}
              />
            </Field>
          )}
          <Field label="Probability (Simulator only, 0–1)">
            <input
              type="number"
              min={0}
              max={1}
              step="0.05"
              value={d.prob ?? ""}
              disabled={readOnly}
              onChange={(e) => onChange({ prob: num(e.target.value) })}
            />
          </Field>
        </>
      ) : (
        <p className="muted small">Only branches leaving a Decision carry conditions.</p>
      )}
      {!readOnly && (
        <button className="danger" onClick={onDelete}>
          Delete arrow
        </button>
      )}
    </div>
  );
}

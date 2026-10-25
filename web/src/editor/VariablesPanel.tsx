// DES-02: the pathway's variables. Tasks read and write them; conditions compare them.

import { useState } from "react";
import type { Variable, VarType } from "./model";

const TYPES: VarType[] = ["int", "float", "bool", "string"];

export function VariablesPanel({
  variables,
  readOnly,
  onChange,
}: {
  variables: Variable[];
  readOnly: boolean;
  onChange: (v: Variable[]) => void;
}) {
  const [name, setName] = useState("");
  const [type, setType] = useState<VarType>("int");
  const valid = /^[A-Za-z_][A-Za-z0-9_]*$/.test(name) && !variables.some((v) => v.name === name);

  return (
    <div className="inspector">
      <h3>Variables</h3>
      {variables.length === 0 && <p className="muted small">No variables yet.</p>}
      <ul className="vars">
        {variables.map((v) => (
          <li key={v.name}>
            <code>{v.name}</code>
            <select
              value={v.type}
              disabled={readOnly}
              onChange={(e) =>
                onChange(variables.map((x) => (x.name === v.name ? { ...x, type: e.target.value as VarType } : x)))
              }
            >
              {TYPES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
            {!readOnly && (
              <button className="ghost" title="Remove" onClick={() => onChange(variables.filter((x) => x.name !== v.name))}>
                ✕
              </button>
            )}
          </li>
        ))}
      </ul>
      {!readOnly && (
        <form
          className="inline"
          onSubmit={(e) => {
            e.preventDefault();
            if (!valid) return;
            onChange([...variables, { name, type }]);
            setName("");
          }}
        >
          <input value={name} placeholder="spo2" onChange={(e) => setName(e.target.value.trim())} />
          <select value={type} onChange={(e) => setType(e.target.value as VarType)}>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <button className="ghost" disabled={!valid}>
            Add
          </button>
        </form>
      )}
    </div>
  );
}

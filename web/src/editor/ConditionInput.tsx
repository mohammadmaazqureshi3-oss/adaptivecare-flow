// DES-03: a branch condition with syntax and type errors shown as the designer types.
// The check runs in the designer service with pathway-core's own parser and type checker,
// so the editor can never disagree with the Verifier about what a condition means.

import { useEffect, useState } from "react";
import { api, type ConditionCheck } from "../api";
import type { Variable } from "./model";

export function ConditionInput({
  value,
  variables,
  disabled,
  onChange,
}: {
  value: string;
  variables: Variable[];
  disabled: boolean;
  onChange: (v: string) => void;
}) {
  const [check, setCheck] = useState<ConditionCheck | null>(null);

  useEffect(() => {
    if (!value.trim()) {
      setCheck(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      api
        .checkCondition(value, variables)
        .then((c) => live && setCheck(c))
        .catch(() => live && setCheck(null));
    }, 300);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [value, variables]);

  const first = check?.errors[0];
  return (
    <div className="condition">
      <textarea
        className={`mono ${check ? (check.ok ? "ok" : "bad") : ""}`}
        rows={2}
        spellCheck={false}
        value={value}
        disabled={disabled}
        placeholder="urgency <= 2 or spo2 < 90"
        onChange={(e) => onChange(e.target.value)}
      />
      {first && (
        <div className="condition-error">
          <pre className="mono">
            {value}
            {"\n"}
            {" ".repeat(Math.min(first.pos, value.length))}^
          </pre>
          {check!.errors.map((e, i) => (
            <div key={i}>
              {e.kind === "syntax" ? "Syntax" : "Type"} error: {e.message}
            </div>
          ))}
        </div>
      )}
      {check?.ok && <div className="condition-ok">✓ valid condition</div>}
      <div className="hint">
        Use <code>and</code>, <code>or</code>, <code>not</code>, comparisons and <code>in [..]</code> over the declared
        variables.
      </div>
    </div>
  );
}

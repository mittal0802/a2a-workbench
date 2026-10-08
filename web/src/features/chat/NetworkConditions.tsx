import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import type { FaultProfile } from "../../lib/types";

/** Display name of a fault profile, e.g. ``flaky_stream`` → "Flaky stream". */
export function profileLabel(profile: FaultProfile): string {
  const name = profile.name || "custom";
  return name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
}

function validate(text: string): FaultProfile | string {
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed !== "object" || parsed === null || !Array.isArray(parsed.rules)) return "it needs a \"rules\" list";
    if (!parsed.rules.every((r: unknown) => typeof r === "object" && r !== null && "kind" in r)) return "every rule needs a \"kind\"";
    return { name: "custom", ...parsed };
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}

/** Choice of injected network failures for the next messages (preset or custom profile). */
export function NetworkConditions({ value, onChange }: { value: FaultProfile | null; onChange: (p: FaultProfile | null) => void }) {
  const [presets, setPresets] = useState<FaultProfile[]>([]);
  const [custom, setCustom] = useState(value && value.name === "custom" ? JSON.stringify(value, null, 2) : "");
  const [mode, setMode] = useState<string>(value ? value.name ?? "custom" : "stable");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api
      .faultPresets()
      .then((p) => alive && setPresets(p))
      .catch(() => alive && setPresets([]));
    return () => {
      alive = false;
    };
  }, []);

  const choose = (name: string) => {
    setMode(name);
    if (name === "custom") return;
    const preset = presets.find((p) => p.name === name);
    onChange(!preset || preset.rules.length === 0 ? null : preset);
  };

  return (
    <div style={{ padding: "0 10px 8px" }}>
      {[...presets, { name: "custom", description: "Write your own fault profile (JSON).", rules: [] }].map((p) => (
        <label key={p.name} className={`choice ${mode === p.name ? "on" : ""}`} style={{ marginTop: 6, padding: "8px 10px" }}>
          <input type="radio" name="faults" className="sr-only" checked={mode === p.name} onChange={() => choose(p.name!)} aria-label={profileLabel(p)} />
          <span className="rd" />
          <div>
            {profileLabel(p)}
            <small>{p.description}</small>
          </div>
        </label>
      ))}
      {mode === "custom" && (
        <>
          <textarea
            aria-label="Custom fault profile"
            className="jsonedit"
            style={{ marginTop: 8 }}
            placeholder='{"rules": [{"kind": "drop_stream", "params": {"after_events": 3}}]}'
            value={custom}
            onChange={(e) => {
              setCustom(e.target.value);
              const result = validate(e.target.value);
              if (typeof result === "string") {
                setError(result);
              } else {
                setError(null);
                onChange(result);
              }
            }}
          />
          {error && custom && <div className="err">That is not a valid profile: {error}</div>}
        </>
      )}
    </div>
  );
}

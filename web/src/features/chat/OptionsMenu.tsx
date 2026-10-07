import * as Popover from "@radix-ui/react-popover";
import { useState } from "react";
import { Switch } from "../../components/Switch";
import type { Agent, SendOptions } from "../../lib/types";

function ChipInput({
  label,
  values,
  onChange,
  suggestions = [],
  placeholder,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
  suggestions?: string[];
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  const listId = `${label.replace(/\W/g, "")}-list`;
  const add = () => {
    const v = draft.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  };
  return (
    <div style={{ padding: "4px 10px 8px" }}>
      <label className="lbl2" style={{ fontSize: 12 }}>
        {label}
        <input
          className="jsonedit"
          style={{ minHeight: 0, marginTop: 4 }}
          value={draft}
          list={listId}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          onBlur={add}
        />
      </label>
      <datalist id={listId}>
        {suggestions.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
        {values.map((v) => (
          <span key={v} className="chipx">
            {v}
            <button aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}>
              ×
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}

/** Popover exposing every client-side send option of an A2A message. */
export function OptionsMenu({
  agent,
  value,
  onChange,
}: {
  agent: Agent;
  value: SendOptions;
  onChange: (v: SendOptions) => void;
}) {
  const caps = agent.card.capabilities ?? {};
  const declared: { uri: string; description?: string; required?: boolean }[] = caps.extensions ?? [];
  const [metaText, setMetaText] = useState(value.message_metadata ? JSON.stringify(value.message_metadata) : "");
  const [metaError, setMetaError] = useState<string | null>(null);
  const set = (patch: Partial<SendOptions>) => onChange({ ...value, ...patch });
  const toggleExt = (uri: string, on: boolean) =>
    set({ extensions: on ? [...value.extensions, uri] : value.extensions.filter((e) => e !== uri) });
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button className="ib" aria-label="Options">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6" />
          </svg>
          Options
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="pop on" side="top" align="start" sideOffset={8} style={{ position: "static", width: 360, maxHeight: "70vh", overflow: "auto" }}>
          <h5>Message options</h5>
          <div className="opt">
            <div>
              Stream replies live
              <small>{caps.streaming ? "SendStreamingMessage" : "This agent doesn't stream"}</small>
            </div>
            <Switch label="Stream replies live" checked={value.stream} disabled={!caps.streaming} onCheckedChange={(v) => set({ stream: v })} />
          </div>
          <div className="opt">
            <div>
              Return immediately<small>don't wait for the task to finish</small>
            </div>
            <Switch label="Return immediately" checked={value.return_immediately} onCheckedChange={(v) => set({ return_immediately: v })} />
          </div>
          <div style={{ padding: "4px 10px 8px" }}>
            <label className="lbl2" style={{ fontSize: 12 }}>
              History to include
              <input
                className="jsonedit"
                style={{ minHeight: 0, marginTop: 4 }}
                type="number"
                min={0}
                placeholder="agent default"
                value={value.history_length ?? ""}
                onChange={(e) => set({ history_length: e.target.value === "" ? null : Math.max(0, parseInt(e.target.value, 10) || 0) })}
              />
            </label>
          </div>
          <ChipInput
            label="Formats I accept"
            values={value.accepted_output_modes}
            onChange={(v) => set({ accepted_output_modes: v })}
            suggestions={agent.card.defaultOutputModes ?? []}
            placeholder="e.g. text/plain"
          />
          <h5>Extensions</h5>
          {declared.map((e) => (
            <div className="opt" key={e.uri}>
              <div>
                {e.description || e.uri}
                {e.required ? " (required)" : ""}
                <small className="mono">{e.uri}</small>
              </div>
              <Switch label={`Activate ${e.uri}`} checked={value.extensions.includes(e.uri)} onCheckedChange={(on) => toggleExt(e.uri, on)} />
            </div>
          ))}
          <ChipInput
            label="Other extension URIs"
            values={value.extensions.filter((x) => !declared.some((d) => d.uri === x))}
            onChange={(others) => set({ extensions: [...value.extensions.filter((x) => declared.some((d) => d.uri === x)), ...others] })}
            placeholder="https://…"
          />
          <h5>Advanced</h5>
          <div style={{ padding: "4px 10px 8px" }}>
            <label className="lbl2" style={{ fontSize: 12 }}>
              Message metadata (JSON object)
              <textarea
                className="jsonedit"
                value={metaText}
                onChange={(e) => {
                  setMetaText(e.target.value);
                  if (!e.target.value.trim()) {
                    setMetaError(null);
                    set({ message_metadata: null });
                    return;
                  }
                  try {
                    const parsed = JSON.parse(e.target.value);
                    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("must be an object");
                    setMetaError(null);
                    set({ message_metadata: parsed });
                  } catch (err) {
                    setMetaError(err instanceof Error ? err.message : "invalid JSON");
                  }
                }}
              />
            </label>
            {metaError && <div className="err">Metadata is not valid: {metaError}</div>}
          </div>
          <ChipInput
            label="Referenced task ids"
            values={value.reference_task_ids}
            onChange={(v) => set({ reference_task_ids: v })}
            placeholder="task id"
          />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

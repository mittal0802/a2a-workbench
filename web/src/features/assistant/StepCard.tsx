import { useState } from "react";
import { Link } from "react-router";
import { Avatar } from "../../components/Avatar";
import { JsonView } from "../../components/JsonView";
import { stateLabel, toneClass } from "../../lib/labels";
import type { AssistantStep } from "../../lib/types";
import { Markdown } from "../chat/PartView";
import type { OutPart } from "./timeline";

function seconds(a?: AssistantStep, b?: AssistantStep): string {
  if (!a || !b) return "";
  return ` · ${((new Date(b.ts).getTime() - new Date(a.ts).getTime()) / 1000).toFixed(1)}s`;
}

/** Renders summarized agent parts: text as Markdown, data as JSON, files as links. */
export function OutParts({ parts }: { parts: OutPart[] }) {
  return (
    <>
      {parts.map((p, i) =>
        p.kind === "text" ? (
          <Markdown key={i} text={p.text ?? ""} />
        ) : p.kind === "data" ? (
          <JsonView key={i} value={p.data} />
        ) : (
          <div key={i}>
            📎 {p.url && /^https?:\/\//i.test(p.url) ? <a href={p.url} target="_blank" rel="noreferrer noopener">{p.name ?? p.url}</a> : (p.name ?? "file")}
            {p.media_type ? ` · ${p.media_type}` : ""}
          </div>
        ),
      )}
    </>
  );
}

/** One agent call: the exact message sent (with ids), what came back, and a link to its conversation. */
export function StepCard({ call, result, rejected }: { call?: AssistantStep; result?: AssistantStep; rejected?: AssistantStep }) {
  const [open, setOpen] = useState(false);
  const agent = call?.data.agent ?? result?.data.agent ?? rejected?.data.agent ?? call?.data.tool ?? "agent";
  const args = (call?.data.arguments ?? {}) as Record<string, unknown>;
  const r = result?.data;
  const pill = rejected
    ? { label: "Not sent", cls: "s-bad" }
    : r
      ? r.kind === "error"
        ? { label: "Error", cls: "s-bad" }
        : (() => {
            const s = stateLabel(r.state ?? (r.kind === "message" ? "completed" : "unspecified"));
            return { label: r.kind === "message" ? "Replied" : s.label, cls: toneClass(s.tone) };
          })()
      : { label: "Calling…", cls: "s-run" };
  const sub = rejected
    ? `not sent: ${rejected.data.rule}`
    : r?.answered_by
      ? `answered by ${r.answered_by === "user" ? "you" : "the assistant"}`
      : call?.data.tool === "get_task" || call?.data.tool === "cancel_task"
        ? call.data.tool
        : r?.state ?? "";
  const ids = [
    args.task_id ? `task_id ${args.task_id}` : null,
    args.context_id ? `context_id ${args.context_id}` : null,
    Array.isArray(args.reference_task_ids) && args.reference_task_ids.length ? `references ${args.reference_task_ids.join(", ")}` : null,
  ].filter(Boolean);
  return (
    <div className={`step ${open ? "open" : ""}`} data-testid="step-card">
      <button className="step-h" style={{ width: "100%", textAlign: "left" }} onClick={() => setOpen(!open)} aria-expanded={open}>
        <Avatar name={agent} size={26} />
        <div>
          {call ? (
            <>
              Asked <b>{agent}</b>
            </>
          ) : (
            <>
              Your reply to <b>{agent}</b>
            </>
          )}
          <br />
          <small>
            {sub}
            {seconds(call, result ?? rejected)}
          </small>
        </div>
        <div className="spacer" />
        <span className={`state ${pill.cls}`}>
          <i />
          {pill.label}
        </span>
      </button>
      <div className="step-b">
        {call && (
          <div>
            → “{String(args.message ?? "")}”{ids.length ? <span className="mono"> · {ids.join(" · ")}</span> : null}
          </div>
        )}
        {args.data !== undefined && <JsonView value={args.data} />}
        {rejected && (
          <div className="err">
            ✕ {rejected.data.message}
            {rejected.data.spec_ref && <div className="no">{rejected.data.spec_ref}</div>}
          </div>
        )}
        {r && (
          <>
            <div className="mono">
              ← {r.kind}
              {r.state ? ` · ${r.state}` : ""}
              {r.task_id ? ` · task_id ${r.task_id}` : ""}
              {r.context_id ? ` · context_id ${r.context_id}` : ""}
            </div>
            {(r.messages ?? []).map((m: string, i: number) => (
              <Markdown key={`m${i}`} text={m} />
            ))}
            {(r.artifacts ?? []).map((a: { name?: string; parts: OutPart[] }, i: number) => (
              <div key={`a${i}`} className="result" style={{ margin: "6px 0" }}>
                <div className="result-h">📦 {a.name || "Result"}</div>
                <div style={{ padding: "6px 12px" }}>
                  <OutParts parts={a.parts} />
                </div>
              </div>
            ))}
            {(r.warnings ?? []).map((w: string, i: number) => (
              <div key={`w${i}`} className="note warn">
                {w}
              </div>
            ))}
            {(r.notes ?? []).map((w: string, i: number) => (
              <div key={`n${i}`} className="no">
                {w}
              </div>
            ))}
            {r.error && <div className="err">{r.error.message}</div>}
            {r.conversation_id && r.agent_id && (
              <Link className="try" to={`/agents/${r.agent_id}/chat?conversation=${r.conversation_id}`}>
                Open this conversation →
              </Link>
            )}
          </>
        )}
      </div>
    </div>
  );
}

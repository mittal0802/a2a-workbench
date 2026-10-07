import { useState } from "react";
import { joinText } from "../../lib/parts";
import { stateLabel } from "../../lib/labels";
import type { TimelineEvent } from "../../lib/types";

/** Plain-language sentence for one timeline event. */
export function describe(e: TimelineEvent): string {
  const d = e.data;
  if (e.kind === "task") return d.state === "submitted" ? "Task created" : `Task: ${stateLabel(d.state).label}`;
  if (e.kind === "status") {
    const text = d.status?.message ? joinText(d.status.message.parts ?? []) : "";
    return text ? `${stateLabel(d.state).label}: “${text}”` : `Status: ${stateLabel(d.state).label}`;
  }
  if (e.kind === "artifact") {
    const name = d.assembled?.name || d.artifact?.artifactId || "result";
    if (d.last_chunk) return `Finished “${name}” (${d.assembled?.parts?.length ?? 0} pieces)`;
    return d.append ? `Received more of “${name}”` : `Started sending “${name}”`;
  }
  if (e.kind === "message") return "Replied with a message";
  if (e.kind === "error") return `Error: ${d.message}`;
  return e.kind;
}

/** Collapsible list of everything that happened during one agent turn. */
export function EventLog({ events, onInspect }: { events: TimelineEvent[]; onInspect?: (exchangeId: string) => void }) {
  const [open, setOpen] = useState(false);
  if (events.length === 0) return null;
  const start = new Date(events[0].ts).getTime();
  return (
    <>
      <button className="more" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? "▾" : "▸"} Show what happened · {events.length} update{events.length === 1 ? "" : "s"}
      </button>
      {open && (
        <div className="evs on">
          {events.map((e) => (
            <div key={e.seq}>
              <span className="t">{((new Date(e.ts).getTime() - start) / 1000).toFixed(1)}s</span>
              <span style={{ flex: 1 }}>{describe(e)}</span>
              {e.exchange_id && onInspect && (
                <button className="ib" style={{ padding: "0 6px" }} onClick={() => onInspect(e.exchange_id!)}>
                  raw
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

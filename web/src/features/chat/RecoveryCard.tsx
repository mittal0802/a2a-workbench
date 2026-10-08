import { stateLabel } from "../../lib/labels";
import type { ConnectionLostData, RecoveryData } from "../../lib/types";

/** Shown when the connection dropped while the task was still running. */
export function ConnectionLostCard({
  data,
  onResubscribe,
  onCheck,
}: {
  data: ConnectionLostData;
  onResubscribe?: () => void;
  onCheck?: () => void;
}) {
  return (
    <div className="ask" style={{ background: "var(--red-soft)" }} role="alert">
      <div className="lbl" style={{ color: "var(--red)" }}>
        ● Connection lost while the agent was {stateLabel(data.last_state).label.toLowerCase()}
      </div>
      <div className="no" style={{ fontSize: 12.5 }}>
        {data.message}. The task may still be running on the agent.
      </div>
      <div className="chips">
        <button className="chipbtn" onClick={onResubscribe} title="SubscribeToTask">
          Resubscribe
        </button>
        <button className="chipbtn" onClick={onCheck} title="GetTask">
          Check status
        </button>
      </div>
    </div>
  );
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Plain-language result of a resubscribe or status check. */
export function RecoveredSummary({ data }: { data: RecoveryData }) {
  const good = (data.method === "get_task" || data.snapshot_first) && data.duplicate_events === 0;
  const items: { ok: boolean; text: string }[] = [];
  if (data.method === "subscribe")
    items.push(
      data.snapshot_first
        ? { ok: true, text: "The current task arrived first, as the spec requires" }
        : { ok: false, text: `The stream did not start with the current task (first: ${data.first_event ?? "nothing"})` },
    );
  items.push(
    data.duplicate_events === 0
      ? { ok: true, text: "No duplicates" }
      : { ok: false, text: plural(data.duplicate_events, "duplicate update", "duplicate updates") },
  );
  if (data.missed_states.length)
    items.push({ ok: true, text: `Caught up on: ${data.missed_states.map((s) => stateLabel(s).label).join(", ")}` });
  if (data.missed_artifacts.length)
    items.push({ ok: true, text: plural(data.missed_artifacts.length, "result you missed", "results you missed") });
  return (
    <div className={`note ${good ? "ok" : "warn"}`} style={{ display: "block" }}>
      <b>{good ? "Back in sync" : "Recovered, with issues"}</b>
      <span className="no">
        {" "}
        · via {data.method === "subscribe" ? "resubscribe" : "status check"} ·{" "}
        {data.state_after ? stateLabel(data.state_after).label : "unknown state"}
      </span>
      <ul style={{ margin: "6px 0 0 18px" }}>
        {items.map((i) => (
          <li key={i.text} style={{ color: i.ok ? undefined : "var(--amber)" }}>
            {i.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

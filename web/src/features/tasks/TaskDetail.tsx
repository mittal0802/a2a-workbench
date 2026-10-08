import { useState } from "react";
import { JsonView } from "../../components/JsonView";
import { StatePill } from "../../components/StatusPill";
import type { A2ATask } from "../../lib/types";
import { ArtifactCard } from "../chat/ArtifactCard";
import { PartView } from "../chat/PartView";

/** Everything known about one task: state, status message, history and results. */
export function TaskDetail({ task, onClose }: { task: A2ATask; onClose: () => void }) {
  const [raw, setRaw] = useState(false);
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div className="card-h">
        Task <span className="mono">{task.id}</span>
        <StatePill state={task.state} />
        <div className="spacer" />
        <button className="ib" onClick={() => setRaw(!raw)}>
          {raw ? "Hide raw" : "Raw JSON"}
        </button>
        <button className="ib" onClick={onClose} aria-label="Close task">
          ✕
        </button>
      </div>
      <div className="card-b">
        {raw ? (
          <JsonView value={task} />
        ) : (
          <>
            {task.status?.message && (
              <div className="ask" style={{ marginBottom: 10 }}>
                {task.status.message.parts.map((p, i) => (
                  <PartView key={i} part={p} />
                ))}
              </div>
            )}
            {(task.history ?? []).map((m, i) => (
              <div key={i} className={`msg ${m.role === "ROLE_USER" ? "mine" : ""}`} style={{ marginBottom: 8 }}>
                <div className="bubble">
                  {m.parts.map((p, j) => (
                    <PartView key={j} part={p} />
                  ))}
                </div>
              </div>
            ))}
            {(task.artifacts ?? []).map((a) => (
              <ArtifactCard key={a.artifactId} artifact={a} complete />
            ))}
            {!task.history?.length && !task.artifacts?.length && (
              <p className="no">This task has no history or results (try including results, or more history).</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

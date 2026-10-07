import { Avatar } from "../../components/Avatar";
import { INTERRUPTED, RUNNING } from "../../lib/labels";
import type { AgentTurn, UserTurn } from "../../lib/timeline";
import type { A2APart, ErrorData } from "../../lib/types";
import { ArtifactCard } from "./ArtifactCard";
import { AskCard } from "./AskCard";
import { EventLog } from "./EventLog";
import { PartView } from "./PartView";
import { TaskProgress } from "./TaskProgress";

const ERROR_TITLE: Record<ErrorData["category"], string> = {
  transport: "Couldn't reach the agent",
  auth: "The agent needs you to sign in",
  protocol: "The agent returned an error",
  workbench: "Something went wrong in the Workbench",
};

/** A message the user sent. */
export function UserBubble({ turn }: { turn: UserTurn }) {
  const parts: A2APart[] = turn.event.data.message?.parts ?? [];
  return (
    <div className="msg mine">
      <div className="bubble">
        {parts.map((p, i) => (
          <PartView key={i} part={p} />
        ))}
      </div>
    </div>
  );
}

/** Everything the agent did in response to one user message. */
export function AgentBubble({
  turn,
  agentName,
  onInspect,
}: {
  turn: AgentTurn;
  agentName: string;
  onInspect?: (exchangeId: string) => void;
}) {
  const first = turn.events[0];
  const last = turn.events[turn.events.length - 1];
  const seconds = first && last ? (new Date(last.ts).getTime() - new Date(first.ts).getTime()) / 1000 : 0;
  const completeIds = new Set(
    turn.events.filter((e) => e.kind === "artifact" && e.data.last_chunk).map((e) => e.data.assembled.artifactId),
  );
  const finished = turn.current !== null && !RUNNING.has(turn.current);
  const exchangeOf = (artifactId: string) =>
    [...turn.events].reverse().find((e) => e.kind === "artifact" && e.data.assembled?.artifactId === artifactId)?.exchange_id;
  return (
    <div className="msg">
      <Avatar name={agentName} size={32} />
      <div className="bubble" style={{ flex: 1, minWidth: 0 }}>
        <div className="name">
          {agentName} <span>· {seconds.toFixed(1)}s</span>
        </div>
        {turn.states.length > 0 && <TaskProgress states={turn.states} current={turn.current} />}
        {turn.messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 8 }}>
            {m.parts.map((p, j) => (
              <PartView key={j} part={p} />
            ))}
          </div>
        ))}
        {Object.values(turn.artifacts).map((a) => {
          const exchangeId = exchangeOf(a.artifactId);
          return (
            <ArtifactCard
              key={a.artifactId}
              artifact={a}
              complete={completeIds.has(a.artifactId) || finished}
              onInspect={exchangeId && onInspect ? () => onInspect(exchangeId) : undefined}
            />
          );
        })}
        {turn.current && INTERRUPTED.has(turn.current) ? (
          <AskCard message={turn.statusMessage} state={turn.current} />
        ) : (
          turn.statusMessage && (
            <div style={{ color: turn.current && RUNNING.has(turn.current) ? "var(--muted)" : undefined, marginBottom: 6 }}>
              {turn.statusMessage.parts.map((p, i) => (
                <PartView key={i} part={p} />
              ))}
            </div>
          )
        )}
        {turn.error && (
          <div className="err" role="alert">
            <b>{ERROR_TITLE[turn.error.category]}</b>
            <div>
              {turn.error.reason ? `${turn.error.reason} ` : ""}
              {turn.error.code !== undefined && turn.error.code !== null ? `(${turn.error.code}) ` : ""}
              {turn.error.message}
            </div>
          </div>
        )}
        <EventLog events={turn.events} onInspect={onInspect} />
      </div>
    </div>
  );
}

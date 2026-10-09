import type { A2AArtifact, A2AMessage, ConnectionLostData, ErrorData, RecoveryData, TimelineEvent } from "./types";

export type UserTurn = { kind: "user"; event: TimelineEvent };
export type AgentTurn = {
  kind: "agent";
  taskId: string | null;
  contextId: string | null;
  states: string[];
  current: string | null;
  artifacts: Record<string, A2AArtifact>;
  messages: A2AMessage[];
  statusMessage: A2AMessage | null;
  events: TimelineEvent[];
  error: ErrorData | null;
  lost: ConnectionLostData | null;
  recovered: RecoveryData | null;
  pushes: TimelineEvent[];
};
export type Turn = UserTurn | AgentTurn;

const emptyAgent = (): AgentTurn => ({
  kind: "agent",
  taskId: null,
  contextId: null,
  states: [],
  current: null,
  artifacts: {},
  messages: [],
  statusMessage: null,
  events: [],
  error: null,
  lost: null,
  recovered: null,
  pushes: [],
});

const FINISHED = new Set(["completed", "failed", "canceled", "rejected"]);

/** Records a push delivery on the turn of its task; its state advances the turn unless the turn already finished. */
function applyPush(turn: AgentTurn, e: TimelineEvent) {
  turn.pushes.push(e);
  turn.taskId = turn.taskId ?? e.task_id;
  const state = e.data.state as string | null;
  if (!state || (turn.current && FINISHED.has(turn.current))) return;
  if (turn.states[turn.states.length - 1] !== state) turn.states.push(state);
  turn.current = state;
}

/** Group a conversation's events into alternating user and agent turns, ordered by seq.
 *
 * Push events join the turn of the task they report on, wherever it is.
 */
export function buildTurns(events: TimelineEvent[]): Turn[] {
  const turns: Turn[] = [];
  let agent: AgentTurn | null = null;
  for (const e of [...events].sort((a, b) => a.seq - b.seq)) {
    if (e.kind === "user_message") {
      turns.push({ kind: "user", event: e });
      agent = null;
      continue;
    }
    if (e.kind === "push") {
      const owner = [...turns].reverse().find((t): t is AgentTurn => t.kind === "agent" && !!e.task_id && t.taskId === e.task_id);
      if (owner) {
        owner.events.push(e);
        applyPush(owner, e);
        continue;
      }
    }
    if (!agent) {
      agent = emptyAgent();
      turns.push(agent);
    }
    agent.events.push(e);
    agent.taskId = e.task_id ?? agent.taskId;
    agent.contextId = e.context_id ?? agent.contextId;
    if (e.kind === "task" || e.kind === "status") {
      const state = e.data.state as string;
      if (agent.states[agent.states.length - 1] !== state) agent.states.push(state);
      agent.current = state;
      const msg = (e.kind === "status" ? e.data.status?.message : e.data.task?.status?.message) as
        | A2AMessage
        | undefined;
      agent.statusMessage = msg ?? null;
      if (e.kind === "task") {
        for (const a of (e.data.task?.artifacts ?? []) as A2AArtifact[]) agent.artifacts[a.artifactId] = a;
      }
    }
    if (e.kind === "artifact") {
      const a = e.data.assembled as A2AArtifact;
      agent.artifacts[a.artifactId] = a;
    }
    if (e.kind === "message") agent.messages.push(e.data.message as A2AMessage);
    if (e.kind === "error") agent.error = e.data as ErrorData;
    if (e.kind === "connection_lost") {
      agent.lost = e.data as ConnectionLostData;
      agent.recovered = null;
    }
    if (e.kind === "recovered") agent.recovered = e.data as RecoveryData;
    if (e.kind === "push") applyPush(agent, e);
  }
  return turns;
}

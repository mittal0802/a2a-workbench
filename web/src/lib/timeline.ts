import type { A2AArtifact, A2AMessage, ErrorData, TimelineEvent } from "./types";

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
});

/** Group a conversation's events into alternating user and agent turns, ordered by seq. */
export function buildTurns(events: TimelineEvent[]): Turn[] {
  const turns: Turn[] = [];
  let agent: AgentTurn | null = null;
  for (const e of [...events].sort((a, b) => a.seq - b.seq)) {
    if (e.kind === "user_message") {
      turns.push({ kind: "user", event: e });
      agent = null;
      continue;
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
      if (msg) agent.statusMessage = msg;
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
  }
  return turns;
}

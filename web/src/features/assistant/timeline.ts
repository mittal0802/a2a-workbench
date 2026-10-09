import type { AssistantStep } from "../../lib/types";

export type OutPart = { kind: string; text?: string; data?: unknown; url?: string; name?: string; media_type?: string };

/** One thing to draw in the Assistant thread. */
export type ThreadItem =
  | { type: "user"; step: AssistantStep }
  | { type: "think"; step: AssistantStep }
  | { type: "call"; call?: AssistantStep; result?: AssistantStep; rejected?: AssistantStep; outputs: AssistantStep[] }
  | { type: "agent"; agent: string; agentId: string; outputs: AssistantStep[] }
  | { type: "pause"; step: AssistantStep }
  | { type: "final"; step: AssistantStep }
  | { type: "note"; step: AssistantStep };

/** Groups Assistant steps into thread items: each tool call with its outputs and result. */
export function buildThread(steps: AssistantStep[]): ThreadItem[] {
  const items: ThreadItem[] = [];
  let open: Extract<ThreadItem, { type: "call" }> | null = null;
  let loose: AssistantStep[] = [];
  const flushLoose = () => {
    if (loose.length) items.push({ type: "agent", agent: loose[0].data.agent, agentId: loose[0].data.agent_id, outputs: loose });
    loose = [];
  };
  for (const s of steps) {
    if (s.kind === "tool_call") {
      flushLoose();
      open = { type: "call", call: s, outputs: [] };
      items.push(open);
    } else if (s.kind === "agent_output") {
      if (open) open.outputs.push(s);
      else loose.push(s);
    } else if (s.kind === "tool_result" || s.kind === "rejected_call") {
      const target: Extract<ThreadItem, { type: "call" }> = open ?? { type: "call", outputs: loose };
      if (!open) {
        loose = [];
        items.push(target);
      }
      if (s.kind === "tool_result") target.result = s;
      else target.rejected = s;
      open = null;
    } else {
      flushLoose();
      open = null;
      if (s.kind === "user") items.push({ type: "user", step: s });
      else if (s.kind === "assistant") {
        if (s.data.text && (s.data.tool_calls ?? []).length > 0) items.push({ type: "think", step: s });
      } else if (s.kind === "paused") items.push({ type: "pause", step: s });
      else if (s.kind === "done") items.push({ type: "final", step: s });
      else items.push({ type: "note", step: s });
    }
  }
  flushLoose();
  return items;
}

/** Joins an agent's output steps into parts: streamed chunks of one artifact become one text. */
export function outputParts(outputs: AssistantStep[]): OutPart[] {
  const parts: OutPart[] = [];
  const lastText: Record<string, number> = {};
  for (const o of outputs) {
    const key = o.data.source === "artifact" ? `a:${o.data.artifact_id}` : null;
    for (const p of (o.data.parts ?? []) as OutPart[]) {
      if (p.kind === "text" && key && o.data.append && lastText[key] !== undefined) {
        const i = lastText[key];
        parts[i] = { ...parts[i], text: (parts[i].text ?? "") + (p.text ?? "") };
      } else {
        parts.push({ ...p });
        if (p.kind === "text" && key) lastText[key] = parts.length - 1;
      }
    }
  }
  return parts;
}

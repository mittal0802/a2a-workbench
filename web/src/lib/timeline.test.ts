import { describe, expect, it } from "vitest";
import { buildTurns } from "./timeline";
import type { TimelineEvent } from "./types";

const ev = (
  seq: number,
  kind: TimelineEvent["kind"],
  data: Record<string, unknown>,
  task_id: string | null = "t1",
): TimelineEvent => ({
  conversation_id: "c", seq, kind, ts: "2026-10-07T00:00:00Z", task_id, context_id: "x", exchange_id: "e", data,
});

describe("buildTurns", () => {
  it("groups agent events after each user message into one turn", () => {
    const turns = buildTurns([
      ev(1, "user_message", { message: { parts: [{ text: "hi" }] } }, null),
      ev(2, "task", { state: "submitted", task: { id: "t1" } }),
      ev(3, "status", { state: "working", status: {} }),
      ev(4, "artifact", { append: false, last_chunk: true, artifact: {}, assembled: { artifactId: "a", parts: [{ text: "x" }] } }),
      ev(5, "status", { state: "completed", status: {} }),
    ]);
    expect(turns.map((t) => t.kind)).toEqual(["user", "agent"]);
    const agent = turns[1];
    if (agent.kind !== "agent") throw new Error();
    expect(agent.states).toEqual(["submitted", "working", "completed"]);
    expect(agent.current).toBe("completed");
    expect(agent.artifacts.a.parts).toEqual([{ text: "x" }]);
  });

  it("keeps only the latest assembled version of each artifact", () => {
    const turns = buildTurns([
      ev(1, "user_message", { message: { parts: [] } }, null),
      ev(2, "artifact", { append: false, last_chunk: false, assembled: { artifactId: "a", parts: [{ text: "1" }] } }),
      ev(3, "artifact", { append: true, last_chunk: true, assembled: { artifactId: "a", parts: [{ text: "1" }, { text: "2" }] } }),
    ]);
    const agent = turns[1];
    if (agent.kind !== "agent") throw new Error();
    expect(agent.artifacts.a.parts).toHaveLength(2);
  });

  it("captures the status message of an interrupted task and errors", () => {
    const turns = buildTurns([
      ev(1, "user_message", { message: { parts: [] } }, null),
      ev(2, "status", { state: "input_required", status: { message: { parts: [{ text: "A or B?" }] } } }),
      ev(3, "error", { category: "transport", message: "down" }),
    ]);
    const agent = turns[1];
    if (agent.kind !== "agent") throw new Error();
    expect(agent.statusMessage?.parts[0]).toEqual({ text: "A or B?" });
    expect(agent.error?.category).toBe("transport");
  });

  it("collects direct agent messages", () => {
    const turns = buildTurns([
      ev(1, "user_message", { message: { parts: [] } }, null),
      ev(2, "message", { message: { role: "ROLE_AGENT", parts: [{ text: "yo" }] } }, null),
    ]);
    const agent = turns[1];
    if (agent.kind !== "agent") throw new Error();
    expect(agent.messages[0].parts[0]).toEqual({ text: "yo" });
  });

  it("orders events by seq even if delivered out of order", () => {
    const turns = buildTurns([
      ev(2, "task", { state: "submitted", task: { id: "t1" } }),
      ev(1, "user_message", { message: { parts: [] } }, null),
    ]);
    expect(turns.map((t) => t.kind)).toEqual(["user", "agent"]);
  });

  it("does not repeat a state that arrives twice in a row", () => {
    const turns = buildTurns([
      ev(1, "user_message", { message: { parts: [] } }, null),
      ev(2, "status", { state: "working", status: {} }),
      ev(3, "status", { state: "working", status: { message: { parts: [{ text: "still" }] } } }),
    ]);
    const agent = turns[1];
    if (agent.kind !== "agent") throw new Error();
    expect(agent.states).toEqual(["working"]);
  });

  it("drops an earlier status message once a later status has none", () => {
    const turns = buildTurns([
      ev(1, "user_message", { message: { parts: [] } }, null),
      ev(2, "status", { state: "working", status: { message: { parts: [{ text: "Working on it" }] } } }),
      ev(3, "status", { state: "completed", status: {} }),
    ]);
    const agent = turns[1];
    if (agent.kind !== "agent") throw new Error();
    expect(agent.statusMessage).toBeNull();
  });
});

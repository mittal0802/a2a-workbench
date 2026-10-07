import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { buildTurns, type AgentTurn } from "../../lib/timeline";
import type { TimelineEvent } from "../../lib/types";
import { AgentBubble } from "./Turn";

const ev = (seq: number, kind: TimelineEvent["kind"], data: Record<string, unknown>, ms = seq * 100): TimelineEvent => ({
  conversation_id: "c", seq, kind, ts: new Date(1_000_000 + ms).toISOString(), task_id: "t", context_id: "x", exchange_id: `e${seq}`, data,
});

function agentTurn(events: TimelineEvent[]): AgentTurn {
  const turn = buildTurns([ev(0, "user_message", { message: { parts: [] } }), ...events])[1];
  if (turn.kind !== "agent") throw new Error("expected agent turn");
  return turn;
}

describe("AgentBubble", () => {
  it("shows the agent's question when input is required", () => {
    const turn = agentTurn([
      ev(1, "task", { state: "submitted", task: { id: "t" } }),
      ev(2, "status", { state: "input_required", status: { message: { parts: [{ text: "A or B?" }] } } }),
    ]);
    render(<AgentBubble turn={turn} agentName="Zoo" />);
    expect(screen.getByText(/waiting for you/i)).toBeInTheDocument();
    expect(screen.getByText("A or B?")).toBeInTheDocument();
  });

  it("explains protocol errors with their code and reason", () => {
    const turn = agentTurn([ev(1, "error", { category: "protocol", message: "Task cannot be canceled", code: -32002, reason: "TASK_NOT_CANCELABLE" })]);
    render(<AgentBubble turn={turn} agentName="Zoo" />);
    expect(screen.getByRole("alert")).toHaveTextContent("The agent returned an error");
    expect(screen.getByRole("alert")).toHaveTextContent("TASK_NOT_CANCELABLE (-32002) Task cannot be canceled");
  });

  it("renders artifacts and opens Inspect on their exchange", async () => {
    const onInspect = vi.fn();
    const turn = agentTurn([
      ev(1, "artifact", { append: false, last_chunk: true, assembled: { artifactId: "a", name: "answer", parts: [{ text: "42" }] } }),
      ev(2, "status", { state: "completed", status: {} }),
    ]);
    render(<AgentBubble turn={turn} agentName="Zoo" onInspect={onInspect} />);
    expect(screen.getByText("42")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /view raw/i }));
    expect(onInspect).toHaveBeenCalledWith("e1");
  });
});

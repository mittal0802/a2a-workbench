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

describe("AgentBubble recovery", () => {
  const lost = { category: "transport", message: "dropped", task_id: "t", last_state: "working" };
  const rec = (over: Record<string, unknown>) => ({
    method: "get_task", first_event: "task", snapshot_first: true, state_before: "working", state_after: "working",
    missed_states: [], missed_artifacts: [], duplicate_events: 0, terminal: false, ...over,
  });

  it("keeps resubscribe available after a status check of a running task", () => {
    const turn = agentTurn([ev(1, "connection_lost", lost), ev(2, "task", { state: "working", task: { id: "t" } }), ev(3, "recovered", rec({}))]);
    render(<AgentBubble turn={turn} agentName="Zoo" onResubscribe={() => {}} />);
    expect(screen.getByRole("button", { name: /resubscribe/i })).toBeInTheDocument();
    expect(screen.getByText(/still working/i)).toBeInTheDocument();
  });

  it("hides the lost card once the task finished", () => {
    const turn = agentTurn([ev(1, "connection_lost", lost), ev(2, "task", { state: "completed", task: { id: "t" } }), ev(3, "recovered", rec({ state_after: "completed", terminal: true }))]);
    render(<AgentBubble turn={turn} agentName="Zoo" />);
    expect(screen.queryByRole("button", { name: /resubscribe/i })).toBeNull();
    expect(screen.getByText(/back in sync/i)).toBeInTheDocument();
  });
});

describe("AgentBubble sign-in prompts", () => {
  it("offers sign in and retry on an auth error", async () => {
    const onSignIn = vi.fn();
    const onRetry = vi.fn();
    const turn = agentTurn([ev(1, "error", { category: "auth", message: "HTTP Error 401", http_status: 401 })]);
    render(<AgentBubble turn={turn} agentName="Zoo" onSignIn={onSignIn} onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/needs you to sign in/i);
    await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onSignIn).toHaveBeenCalled();
    expect(onRetry).toHaveBeenCalled();
  });

  it("offers sign in and continue when the task needs sign-in", async () => {
    const onContinue = vi.fn();
    const turn = agentTurn([ev(1, "status", { state: "auth_required", status: { message: { parts: [{ text: "Please sign in." }] } } })]);
    render(<AgentBubble turn={turn} agentName="Zoo" onSignIn={() => {}} onContinue={onContinue} />);
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(onContinue).toHaveBeenCalled();
  });
  it("renders the agent's text as markdown and copies the raw text", async () => {
    const user = userEvent.setup();
    const turn = agentTurn([
      ev(1, "message", { message: { parts: [{ text: "# Title\n\n**done**" }] } }),
    ]);
    const { container } = render(<AgentBubble turn={turn} agentName="Zoo" />);
    expect(container.querySelector("h1")?.textContent).toBe("Title");
    await user.click(screen.getByRole("button", { name: "Copy raw" }));
    expect(await navigator.clipboard.readText()).toBe("# Title\n\n**done**");
  });

  it("copies the raw text of artifacts and status messages too", async () => {
    const user = userEvent.setup();
    const turn = agentTurn([
      ev(1, "task", { state: "working", task: { id: "t" } }),
      ev(2, "artifact", { append: false, last_chunk: true, artifact: {}, assembled: { artifactId: "a1", name: "r", parts: [{ text: "| a | b |\n|---|---|\n| 1 | 2 |" }] } }),
      ev(3, "status", { state: "completed", status: { message: { parts: [{ text: "All _done_." }] } } }),
    ]);
    const { container } = render(<AgentBubble turn={turn} agentName="Zoo" />);
    expect(container.querySelector("table")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Copy raw" }));
    expect(await navigator.clipboard.readText()).toBe("| a | b |\n|---|---|\n| 1 | 2 |\n\nAll _done_.");
  });
  it("copies a streamed artifact as one text", async () => {
    const user = userEvent.setup();
    const turn = agentTurn([
      ev(1, "task", { state: "working", task: { id: "t" } }),
      ev(2, "artifact", { append: false, last_chunk: true, artifact: {}, assembled: { artifactId: "a1", parts: [{ text: "Stream" }, { text: "ing." }] } }),
    ]);
    render(<AgentBubble turn={turn} agentName="Zoo" />);
    await user.click(screen.getByRole("button", { name: "Copy raw" }));
    expect(await navigator.clipboard.readText()).toBe("Streaming.");
  });
  it("shows push notifications the agent delivered", async () => {
    const user = userEvent.setup();
    const turn = agentTurn([
      ev(1, "task", { state: "working", task: { id: "t" } }),
      ev(2, "push", { kind: "status_update", state: "completed", delivery_id: "d1", payload: { statusUpdate: { taskId: "t" } }, notes: [] }),
    ]);
    render(<AgentBubble turn={turn} agentName="Zoo" />);
    const card = screen.getByTestId("push-d1");
    expect(card.textContent).toMatch(/Notification/);
    expect(card.textContent).toMatch(/Done/);
    await user.click(screen.getByRole("button", { name: /notification/i }));
    expect(card.textContent).toContain('"taskId": "t"');
  });
});

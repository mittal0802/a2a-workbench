import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConnectionLostCard, RecoveredSummary } from "./RecoveryCard";

describe("ConnectionLostCard", () => {
  it("offers resubscribe and check status", async () => {
    const onResubscribe = vi.fn();
    const onCheck = vi.fn();
    render(<ConnectionLostCard data={{ category: "transport", message: "[injected] stream dropped", task_id: "t", last_state: "working" }} onResubscribe={onResubscribe} onCheck={onCheck} />);
    expect(screen.getByText(/connection lost while the agent was working/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /resubscribe/i }));
    await userEvent.click(screen.getByRole("button", { name: /check status/i }));
    expect(onResubscribe).toHaveBeenCalled();
    expect(onCheck).toHaveBeenCalled();
  });
});

describe("RecoveredSummary", () => {
  it("summarizes a clean recovery", () => {
    render(<RecoveredSummary data={{ method: "subscribe", first_event: "task", snapshot_first: true, state_before: "working", state_after: "completed", missed_states: ["completed"], missed_artifacts: [], duplicate_events: 0, terminal: true }} />);
    expect(screen.getByText(/back in sync/i)).toBeInTheDocument();
    expect(screen.getByText(/current task arrived first/i)).toBeInTheDocument();
    expect(screen.getByText(/no duplicates/i)).toBeInTheDocument();
  });

  it("flags problems", () => {
    render(<RecoveredSummary data={{ method: "subscribe", first_event: "status", snapshot_first: false, state_before: "working", state_after: "working", missed_states: [], missed_artifacts: ["b"], duplicate_events: 2, terminal: false }} />);
    expect(screen.getByText(/did not start with the current task/i)).toBeInTheDocument();
    expect(screen.getByText(/2 duplicate updates/i)).toBeInTheDocument();
    expect(screen.getByText(/1 result you missed/i)).toBeInTheDocument();
  });
});

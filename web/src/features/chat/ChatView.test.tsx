import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { ChatView } from "./ChatView";

vi.mock("../../lib/ws", () => ({ getHub: () => ({ subscribe: () => () => {} }) }));

describe("ChatView", () => {
  it("deletes a conversation after confirming", async () => {
    vi.spyOn(api, "listConversations").mockResolvedValue([
      { id: "cv1", agent_id: "ag1", title: "Old chat", origin: "chat", context_id: null, task_id: null, task_state: null },
    ] as never);
    vi.spyOn(api, "getConversation").mockResolvedValue({ conversation: { id: "cv1", last_seq: 0 }, events: [] } as never);
    const del = vi.spyOn(api, "deleteConversation").mockResolvedValue(undefined as never);
    const onChange = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ChatView agent={{ id: "ag1", name: "Zoo", card: { capabilities: {} } } as never} conversationId="cv1" onConversationChange={onChange} />
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Delete conversation Old chat" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(del).toHaveBeenCalledWith("cv1");
    expect(onChange).toHaveBeenCalledWith(null);
  });
});

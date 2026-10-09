import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
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
        <MemoryRouter>
        <ChatView agent={{ id: "ag1", name: "Zoo", card: { capabilities: {} } } as never} conversationId="cv1" onConversationChange={onChange} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Delete conversation Old chat" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(del).toHaveBeenCalledWith("cv1");
    expect(onChange).toHaveBeenCalledWith(null);
  });
});

describe("ChatView sign-in", () => {
  const authFailed = {
    conversation: { id: "cv1", last_seq: 2 },
    events: [
      { conversation_id: "cv1", seq: 1, kind: "user_message", ts: "2026-01-01T00:00:00Z", task_id: null, context_id: null, exchange_id: null,
        data: { message: { parts: [{ text: "hello" }] }, options: {} } },
      { conversation_id: "cv1", seq: 2, kind: "error", ts: "2026-01-01T00:00:01Z", task_id: null, context_id: null, exchange_id: "e1",
        data: { category: "auth", message: "HTTP Error 401: Client error '401 Unauthorized'", http_status: 401 } },
    ],
  };
  const security = (credential: unknown) => ({
    status: credential ? "signed_in" : "sign_in_needed",
    schemes: [{ name: "bearer", type: "http", label: "Bearer token", description: "", details: { scheme: "Bearer" },
      accepts: ["http_bearer"], credential }],
    requirements: [["bearer"]], required_scopes: {}, active: credential ? ["bearer"] : [], missing: credential ? [] : ["bearer"],
  });

  it("opens a sign-in dialog on a 401 and retries the message once signed in", async () => {
    vi.spyOn(api, "listConversations").mockResolvedValue([{ id: "cv1", agent_id: "ag1", title: "hello", origin: "chat" }] as never);
    vi.spyOn(api, "getConversation").mockResolvedValue(authFailed as never);
    const sec = vi.spyOn(api, "security").mockResolvedValue(security(null) as never);
    vi.spyOn(api, "putCredential").mockImplementation(async () => {
      sec.mockResolvedValue(security({ scheme_name: "bearer", kind: "http_bearer", preview: "••••5678", readable: true, expires_at: null, updated_at: "x" }) as never);
      return {} as never;
    });
    const send = vi.spyOn(api, "sendMessage").mockResolvedValue({ accepted: true } as never);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
        <ChatView agent={{ id: "ag1", name: "Zoo", card: { capabilities: {} } } as never} conversationId="cv1" onConversationChange={() => {}} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const dialog = await screen.findByRole("dialog", { name: /sign in to zoo/i });
    expect(within(dialog).getByText(/401/)).toBeInTheDocument();
    await userEvent.type(await within(dialog).findByLabelText(/token/i), "zoo-token-5678");
    await userEvent.click(within(dialog).getByRole("button", { name: /^save$/i }));
    await userEvent.click(await within(dialog).findByRole("button", { name: /retry/i }));
    expect(send).toHaveBeenCalledWith("cv1", [{ kind: "text", text: "hello" }], expect.anything());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("does not reopen by itself once closed, but the Sign in button does", async () => {
    vi.spyOn(api, "listConversations").mockResolvedValue([{ id: "cv1", agent_id: "ag1", title: "hello", origin: "chat" }] as never);
    vi.spyOn(api, "getConversation").mockResolvedValue(authFailed as never);
    vi.spyOn(api, "security").mockResolvedValue(security(null) as never);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
        <ChatView agent={{ id: "ag1", name: "Zoo", card: { capabilities: {} } } as never} conversationId="cv1" onConversationChange={() => {}} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /close/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await userEvent.click(screen.getAllByRole("button", { name: /^sign in$/i })[0]);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});

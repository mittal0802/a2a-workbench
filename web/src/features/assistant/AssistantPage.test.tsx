import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import type { AssistantSession, AssistantStep } from "../../lib/types";
import { AssistantPage } from "./AssistantPage";

const handlers: ((m: Record<string, unknown>) => void)[] = [];
vi.mock("../../lib/ws", () => ({
  getHub: () => ({
    subscribe: (_t: string, _s: number, h: (m: Record<string, unknown>) => void) => {
      handlers.push(h);
      return () => {};
    },
  }),
}));

const agent = { id: "ag1", name: "Zoo agent", base_url: "http://z", card: { skills: [{ id: "echo" }, { id: "ask" }] } };
const session = (over: Partial<AssistantSession> = {}): AssistantSession => ({
  id: "s1", title: "ask", provider: "openai", model: "scripted", response_mode: "rewrite", agent_ids: ["ag1"],
  limits: { max_steps: 12, call_timeout_s: 120, run_timeout_s: 600, token_budget: 200000 }, status: "idle",
  pending: null, created_at: "", updated_at: "", ...over,
});
let n = 0;
const step = (kind: AssistantStep["kind"], data: Record<string, unknown>): AssistantStep => ({
  session_id: "s1", seq: ++n, kind, ts: new Date(1_000_000 + n * 500).toISOString(), data,
});

function renderAt(path: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/assistant/:sessionId?" element={<AssistantPage />} />
          <Route path="/agents/:agentId/:tab?" element={<div>agent page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  handlers.length = 0;
  n = 0;
  vi.restoreAllMocks();
  vi.spyOn(api, "listAgents").mockResolvedValue([agent] as never);
  vi.spyOn(api, "assistantProviders").mockResolvedValue([
    { provider: "anthropic", configured: false, source: "none", default_model: "claude-sonnet-5-5" },
    { provider: "openai", configured: true, source: "stored", preview: "••••0001", base_url: "http://llm/v1" },
    { provider: "gemini", configured: false, source: "none" },
  ] as never);
  vi.spyOn(api, "listAssistantSessions").mockResolvedValue([session()] as never);
});

describe("AssistantPage", () => {
  it("renders the timeline: steps with the exact call, results and the final answer", async () => {
    vi.spyOn(api, "getAssistantSession").mockResolvedValue({
      session: session(),
      steps: [
        step("user", { text: "ask" }),
        step("assistant", { text: "", tool_calls: [{ id: "c1", name: "call_zoo_agent", arguments: { message: "ask" } }] }),
        step("tool_call", { tool: "call_zoo_agent", agent_id: "ag1", agent: "Zoo agent", arguments: { message: "ask" } }),
        step("tool_result", { agent: "Zoo agent", agent_id: "ag1", conversation_id: "cv1", kind: "task", state: "input_required",
          question: "A or B?", task_id: "t1", context_id: "x1", messages: ["A or B?"], artifacts: [], warnings: [], notes: [] }),
        step("tool_call", { tool: "call_zoo_agent", agent_id: "ag1", agent: "Zoo agent", arguments: { message: "B", task_id: "t1", context_id: "x1" } }),
        step("tool_result", { agent: "Zoo agent", agent_id: "ag1", conversation_id: "cv1", kind: "task", state: "completed",
          answered_by: "assistant", task_id: "t1", artifacts: [{ name: "answer", parts: [{ kind: "text", text: "You chose: B" }] }],
          warnings: ["A2A §3.7: results SHOULD be artifacts"], notes: [], messages: [] }),
        step("done", { text: "**Done**: You chose B" }),
      ],
    } as never);
    renderAt("/assistant/s1");
    expect(await screen.findByText("ask", { selector: ".mine .bubble *" })).toBeInTheDocument();
    const cards = await screen.findAllByTestId("step-card");
    expect(cards).toHaveLength(2);
    expect(within(cards[1]).getByText(/answered by the assistant/i)).toBeInTheDocument();
    await userEvent.click(within(cards[1]).getByRole("button", { name: /asked zoo agent/i }));
    expect(within(cards[1]).getAllByText(/task_id t1/).length).toBeGreaterThan(0);
    expect(within(cards[1]).getByText("You chose: B")).toBeInTheDocument();
    expect(within(cards[1]).getByText(/§3.7/)).toBeInTheDocument();
    expect(within(cards[1]).getByRole("link", { name: /open this conversation/i })).toHaveAttribute(
      "href", "/agents/ag1/chat?conversation=cv1");
    expect(document.querySelector(".final strong")?.textContent).toBe("Done");
  });

  it("shows a rejected call with the rule and the spec section", async () => {
    vi.spyOn(api, "getAssistantSession").mockResolvedValue({
      session: session(),
      steps: [step("tool_call", { tool: "call_zoo_agent", agent: "Zoo agent", agent_id: "ag1", arguments: { message: "x", context_id: "made-up" } }),
        step("rejected_call", { tool: "call_zoo_agent", agent: "Zoo agent", rule: "context_not_issued", message: "never returned", spec_ref: "A2A §3.4.1" })],
    } as never);
    renderAt("/assistant/s1");
    const card = await screen.findByTestId("step-card");
    expect(within(card).getByText("Not sent")).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button"));
    expect(within(card).getByText(/A2A §3.4.1/)).toBeInTheDocument();
  });

  it("sends a message and switches the response mode", async () => {
    vi.spyOn(api, "getAssistantSession").mockResolvedValue({ session: session(), steps: [] } as never);
    const send = vi.spyOn(api, "sendAssistantMessage").mockResolvedValue({ accepted: true } as never);
    const patch = vi.spyOn(api, "patchAssistantSession").mockResolvedValue(session({ response_mode: "pass_through" }) as never);
    renderAt("/assistant/s1");
    await userEvent.type(await screen.findByPlaceholderText(/ask the assistant/i), "echo hi{Enter}");
    expect(send).toHaveBeenCalledWith("s1", "echo hi");
    await userEvent.click(screen.getByRole("button", { name: /agents speak directly/i }));
    expect(patch).toHaveBeenCalledWith("s1", { response_mode: "pass_through" });
  });

  it("pass-through: shows the agent's question verbatim and replies to the agent", async () => {
    vi.spyOn(api, "getAssistantSession").mockResolvedValue({
      session: session({ response_mode: "pass_through", status: "awaiting_user",
        pending: { reason: "input_required", agent: "Zoo agent", agent_id: "ag1", question: "Which **option**?" } }),
      steps: [
        step("agent_output", { agent: "Zoo agent", agent_id: "ag1", source: "status", parts: [{ kind: "text", text: "Which **option**?" }] }),
        step("paused", { reason: "input_required", agent: "Zoo agent", agent_id: "ag1", question: "Which **option**?" }),
      ],
    } as never);
    const send = vi.spyOn(api, "sendAssistantMessage").mockResolvedValue({ accepted: true } as never);
    renderAt("/assistant/s1");
    expect((await screen.findAllByText("option", { selector: "strong" })).length).toBeGreaterThan(0);
    const box = screen.getByPlaceholderText(/reply to zoo agent/i);
    await userEvent.type(box, "A{Enter}");
    expect(send).toHaveBeenCalledWith("s1", "A");
  });

  it("sign-in pause links to the agent's Security tab and Continue resumes", async () => {
    vi.spyOn(api, "getAssistantSession").mockResolvedValue({
      session: session({ status: "awaiting_sign_in", pending: { reason: "auth_required", agent: "Zoo agent", agent_id: "ag1", question: "Needs booking.write" } }),
      steps: [step("paused", { reason: "auth_required", agent: "Zoo agent", agent_id: "ag1", question: "Needs booking.write" })],
    } as never);
    const resume = vi.spyOn(api, "resumeAssistantSession").mockResolvedValue({ accepted: true } as never);
    renderAt("/assistant/s1");
    expect(await screen.findByRole("link", { name: /sign in/i })).toHaveAttribute("href", "/agents/ag1/security");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(resume).toHaveBeenCalledWith("s1");
  });

  it("live steps arrive over the WebSocket", async () => {
    vi.spyOn(api, "getAssistantSession").mockResolvedValue({ session: session({ status: "running" }), steps: [] } as never);
    renderAt("/assistant/s1");
    await waitFor(() => expect(handlers.length).toBeGreaterThan(0));
    handlers.forEach((h) => h({ topic: "assistant:s1", type: "step", step: step("done", { text: "Live answer" }) }));
    expect(await screen.findByText("Live answer")).toBeInTheDocument();
  });

  it("new chat: needs a configured provider, then creates the session on the first message", async () => {
    vi.spyOn(api, "listAssistantSessions").mockResolvedValue([] as never);
    const create = vi.spyOn(api, "createAssistantSession").mockResolvedValue(session() as never);
    vi.spyOn(api, "sendAssistantMessage").mockResolvedValue({ accepted: true } as never);
    vi.spyOn(api, "getAssistantSession").mockResolvedValue({ session: session(), steps: [] } as never);
    renderAt("/assistant");
    await userEvent.selectOptions(await screen.findByLabelText(/provider/i), "openai");
    await userEvent.type(screen.getByLabelText(/^model$/i), "scripted");
    await userEvent.type(screen.getByPlaceholderText(/ask the assistant/i), "echo hi{Enter}");
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({
      provider: "openai", model: "scripted", agent_ids: ["ag1"], response_mode: "rewrite" })));
  });

  it("provider settings never show a stored key and save a new one", async () => {
    vi.spyOn(api, "getAssistantSession").mockResolvedValue({ session: session(), steps: [] } as never);
    const put = vi.spyOn(api, "putAssistantProvider").mockResolvedValue({} as never);
    renderAt("/assistant/s1");
    await userEvent.click(await screen.findByRole("button", { name: /model/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/••••0001/)).toBeInTheDocument();
    expect((within(dialog).getByLabelText(/api key/i) as HTMLInputElement).value).toBe("");
    await userEvent.type(within(dialog).getByLabelText(/api key/i), "sk-new");
    await userEvent.click(within(dialog).getByRole("button", { name: /save key/i }));
    expect(put).toHaveBeenCalledWith("openai", { api_key: "sk-new", base_url: "http://llm/v1" });
  });
  it("sends a base URL only for OpenAI-compatible providers", async () => {
    vi.spyOn(api, "listAssistantSessions").mockResolvedValue([] as never);
    const put = vi.spyOn(api, "putAssistantProvider").mockResolvedValue({} as never);
    renderAt("/assistant");
    await userEvent.selectOptions(await screen.findByLabelText(/provider/i), "openai");
    await userEvent.click(screen.getByRole("button", { name: /model/i }));
    let dialog = await screen.findByRole("dialog");
    await userEvent.clear(within(dialog).getByLabelText(/base url/i));
    await userEvent.type(within(dialog).getByLabelText(/base url/i), "http://other/v1");
    await userEvent.click(within(dialog).getByRole("button", { name: /close/i }));
    await userEvent.selectOptions(screen.getByLabelText(/provider/i), "anthropic");
    await userEvent.click(screen.getByRole("button", { name: /model/i }));
    dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/api key/i), "sk-ant");
    await userEvent.click(within(dialog).getByRole("button", { name: /save key/i }));
    expect(put).toHaveBeenLastCalledWith("anthropic", { api_key: "sk-ant", base_url: null });
  });
});

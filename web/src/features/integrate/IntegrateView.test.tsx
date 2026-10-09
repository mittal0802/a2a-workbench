import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { IntegrateView } from "./IntegrateView";

const snippet = (target: string, code: string) => ({
  target, language: "python", install: `pip install ${target}`, code, env: { A2A_BEARER_TOKEN: "Bearer token for scheme 'bearer'" },
});
const guide = {
  agent_id: "ag1", agent: "Zoo", card_url: "http://z/.well-known/agent-card.json",
  snippets: {
    sdk: snippet("sdk", "async def call_agent(): ..."), adk: snippet("adk", "RemoteA2aAgent(...)"),
    langgraph: snippet("langgraph", "create_react_agent(...)"), openai: snippet("openai", "@function_tool"),
    claude: snippet("claude", "create_sdk_mcp_server(...)"),
  },
  guidance: ["Keep the context_id the agent returns (A2A §3.4.1)."],
  readiness: [
    { level: "spec", code: "skill_field_missing", message: "Skill 2 has no tags.", path: "skills[2].tags", spec_ref: "a2a.proto AgentSkill" },
    { level: "advice", code: "skill_without_examples", message: "Skill 'x' has no examples.", path: "skills[x].examples", spec_ref: null },
  ],
};

describe("IntegrateView", () => {
  it("switches targets, copies code and lists env vars, guidance and readiness", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "integration").mockResolvedValue(guide as never);
    render(<QueryClientProvider client={new QueryClient()}><IntegrateView agentId="ag1" /></QueryClientProvider>);
    expect(await screen.findByText(/async def call_agent/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "LangGraph / LangChain" }));
    expect(screen.getByText(/create_react_agent/)).toBeInTheDocument();
    expect(screen.getByText("pip install langgraph")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy code" }));
    expect(await navigator.clipboard.readText()).toBe("create_react_agent(...)");
    expect(screen.getByText("A2A_BEARER_TOKEN")).toBeInTheDocument();
    expect(screen.getByText(/Keep the context_id/)).toBeInTheDocument();
    expect(screen.getByText("Spec issue")).toBeInTheDocument();
    expect(screen.getByText("Advice")).toBeInTheDocument();
    expect(screen.getByText(/a2a.proto AgentSkill/)).toBeInTheDocument();
  });
});

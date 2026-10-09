import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { AgentPage } from "./AgentPage";

vi.mock("../chat/ChatView", () => ({
  ChatView: ({ conversationId }: { conversationId: string | null }) => <div>chat:{conversationId ?? "none"}</div>,
}));
vi.mock("../inspect/InspectDrawer", () => ({ InspectDrawer: () => null }));
vi.mock("../about/AboutView", () => ({ AboutView: ({ footer }: { footer?: React.ReactNode }) => <div>about{footer}</div> }));

describe("AgentPage", () => {
  it("opens the conversation named in the URL", async () => {
    vi.spyOn(api, "getAgent").mockResolvedValue({ id: "ag1", name: "Zoo", base_url: "http://z", card: {}, interfaces: [] } as never);
    vi.spyOn(api, "security").mockResolvedValue({ status: "not_required" } as never);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/agents/ag1/chat?conversation=cv9"]}>
          <Routes>
            <Route path="/agents/:agentId/:tab?" element={<AgentPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("chat:cv9")).toBeInTheDocument();
  });
  it("removes the agent from the About tab after confirming", async () => {
    vi.spyOn(api, "getAgent").mockResolvedValue({ id: "ag1", name: "Zoo", base_url: "http://z", card: {}, interfaces: [] } as never);
    vi.spyOn(api, "security").mockResolvedValue({ status: "not_required" } as never);
    const del = vi.spyOn(api, "deleteAgent").mockResolvedValue(undefined as never);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/agents/ag1/about"]}>
          <Routes>
            <Route path="/agents/:agentId/:tab?" element={<AgentPage />} />
            <Route path="/" element={<div>home</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Remove agent" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(del).toHaveBeenCalledWith("ag1");
    expect(await screen.findByText("home")).toBeInTheDocument();
  });
});

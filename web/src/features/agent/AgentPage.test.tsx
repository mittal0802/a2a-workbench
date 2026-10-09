import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { AgentPage } from "./AgentPage";

vi.mock("../chat/ChatView", () => ({
  ChatView: ({ conversationId }: { conversationId: string | null }) => <div>chat:{conversationId ?? "none"}</div>,
}));
vi.mock("../inspect/InspectDrawer", () => ({ InspectDrawer: () => null }));

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
});

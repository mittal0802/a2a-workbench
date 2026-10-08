import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { SecurityView } from "./SecurityView";

const overview = (over: Record<string, unknown> = {}) => ({
  status: "sign_in_needed",
  requirements: [["apiKey", "bearer"]],
  active: [],
  missing: ["apiKey", "bearer"],
  schemes: [
    { name: "apiKey", type: "apiKey", label: "API key", description: "", details: { location: "header", name: "X-API-Key" }, accepts: ["api_key"], credential: null },
    { name: "basic", type: "http", label: "Username & password", description: "", details: { scheme: "Basic" }, accepts: ["http_basic"], credential: null },
    { name: "bearer", type: "http", label: "Bearer token", description: "", details: { scheme: "Bearer" }, accepts: ["http_bearer"], credential: { scheme_name: "bearer", kind: "http_bearer", preview: "••••5678", readable: true, expires_at: null, updated_at: "" } },
    { name: "mtls", type: "mutualTLS", label: "Client certificate", description: "", details: {}, accepts: ["mtls"], credential: null },
  ],
  ...over,
});

function setup(data = overview()) {
  vi.spyOn(api, "security").mockResolvedValue(data as never);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SecurityView agentId="ag" />
    </QueryClientProvider>,
  );
}

describe("SecurityView", () => {
  it("explains what the agent needs and the current status", async () => {
    setup();
    expect(await screen.findByText(/sign-in needed/i)).toBeInTheDocument();
    expect(screen.getByText(/API key and Bearer token/)).toBeInTheDocument();
    expect(screen.getByText(/sent in the X-API-Key header/i)).toBeInTheDocument();
    expect(screen.getByText("••••5678")).toBeInTheDocument();
  });

  it("saves an API key", async () => {
    setup();
    const put = vi.spyOn(api, "putCredential").mockResolvedValue({} as never);
    const card = (await screen.findByRole("heading", { name: "API key" })).closest(".card") as HTMLElement;
    await userEvent.type(within(card).getByLabelText(/^api key$/i), "k-123");
    await userEvent.click(within(card).getByRole("button", { name: /save/i }));
    expect(put).toHaveBeenCalledWith("ag", "apiKey", { kind: "api_key", value: "k-123" });
  });

  it("saves username and password", async () => {
    setup();
    const put = vi.spyOn(api, "putCredential").mockResolvedValue({} as never);
    const card = (await screen.findByRole("heading", { name: "Username & password" })).closest(".card") as HTMLElement;
    await userEvent.type(within(card).getByLabelText(/username/i), "zoo");
    await userEvent.type(within(card).getByLabelText(/password/i), "pw");
    await userEvent.click(within(card).getByRole("button", { name: /save/i }));
    expect(put).toHaveBeenCalledWith("ag", "basic", { kind: "http_basic", username: "zoo", password: "pw" });
  });

  it("removes a saved credential", async () => {
    setup();
    const del = vi.spyOn(api, "deleteCredential").mockResolvedValue(undefined as never);
    const card = (await screen.findByRole("heading", { name: "Bearer token" })).closest(".card") as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: /remove/i }));
    expect(del).toHaveBeenCalledWith("ag", "bearer");
  });

  it("says when no sign-in is required", async () => {
    setup(overview({ status: "not_required", requirements: [], schemes: [], missing: [] }));
    expect(await screen.findByText(/doesn.t require sign-in/i)).toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { NotificationsView } from "./NotificationsView";

const handlers: ((m: Record<string, unknown>) => void)[] = [];
vi.mock("../../lib/ws", () => ({
  getHub: () => ({
    subscribe: (_t: string, _s: number, h: (m: Record<string, unknown>) => void) => {
      handlers.push(h);
      return () => {};
    },
  }),
}));

const agent = { id: "ag1", name: "Zoo", card: { capabilities: { pushNotifications: true } } };
const delivery = (over: Record<string, unknown> = {}) => ({
  id: "d1", hook_id: "h1", agent_id: "ag1", received_at: "2026-10-09T10:00:00Z", verdict: "accepted", reasons: [],
  notes: ["No token received."], duplicate: false, kind: "status_update", task_id: "t1", state: "completed",
  headers: { authorization: "••••", "content-type": "application/json" }, payload: { statusUpdate: { taskId: "t1" } }, ...over,
});

function setup(a = agent) {
  render(<QueryClientProvider client={new QueryClient()}><NotificationsView agent={a as never} /></QueryClientProvider>);
}

beforeEach(() => {
  handlers.length = 0;
  vi.restoreAllMocks();
  vi.spyOn(api, "listTasks").mockResolvedValue({ tasks: [{ id: "t1", status: { state: "TASK_STATE_WORKING" }, state: "working" }], next_page_token: null, page_size: 50, total_size: 1 } as never);
  vi.spyOn(api, "pushDeliveries").mockResolvedValue([] as never);
  vi.spyOn(api, "publicUrl").mockResolvedValue({ public_base_url: "http://127.0.0.1:8484", source: "local", tunnel_running: false, cloudflared_installed: false } as never);
});

describe("NotificationsView", () => {
  it("creates a Workbench webhook config for a task, lists and deletes it", async () => {
    const list = vi.spyOn(api, "listPushConfigs").mockResolvedValue({ configs: [], next_page_token: null } as never);
    const create = vi.spyOn(api, "createPushConfig").mockResolvedValue({ config: { id: "h1", url: "http://127.0.0.1:8484/hooks/h1", token: "••••" }, hook: { id: "h1" } } as never);
    const del = vi.spyOn(api, "deletePushConfig").mockResolvedValue(undefined as never);
    setup();
    await screen.findByRole("option", { name: /^t1/ });
    await userEvent.selectOptions(screen.getByLabelText(/task/i), "t1");
    expect(screen.getByText(/http:\/\/127\.0\.0\.1:8484/)).toBeInTheDocument();
    list.mockResolvedValue({ configs: [{ id: "h1", taskId: "t1", url: "http://127.0.0.1:8484/hooks/h1", token: "••••" }], next_page_token: null } as never);
    await userEvent.click(screen.getByRole("button", { name: /create config/i }));
    expect(create).toHaveBeenCalledWith("ag1", "t1", { webhook: "workbench" });
    expect(await screen.findByText("h1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /delete config h1/i }));
    await userEvent.click(screen.getByRole("button", { name: "Delete", exact: true } as never));
    expect(del).toHaveBeenCalledWith("ag1", "t1", "h1");
  });

  it("creates a config for your own webhook", async () => {
    vi.spyOn(api, "listPushConfigs").mockResolvedValue({ configs: [], next_page_token: null } as never);
    const create = vi.spyOn(api, "createPushConfig").mockResolvedValue({ config: { id: "c2" }, hook: null } as never);
    setup();
    await screen.findByRole("option", { name: /^t1/ });
    await userEvent.selectOptions(screen.getByLabelText(/task/i), "t1");
    await userEvent.click(screen.getByLabelText(/my own webhook/i));
    await userEvent.type(screen.getByLabelText(/webhook url/i), "https://hooks.example/a");
    await userEvent.type(screen.getByLabelText(/^token$/i), "tok");
    await userEvent.type(screen.getByLabelText("Credentials"), "cred");
    await userEvent.click(screen.getByRole("button", { name: /create config/i }));
    expect(create).toHaveBeenCalledWith("ag1", "t1", {
      webhook: "custom", url: "https://hooks.example/a", token: "tok", auth_scheme: "Bearer", auth_credentials: "cred",
    });
  });

  it("shows deliveries with verdict and reasons, live", async () => {
    vi.spyOn(api, "pushDeliveries").mockResolvedValue([delivery({ id: "d0", verdict: "rejected", reasons: ["unauthenticated"], payload: null })] as never);
    setup();
    expect(await screen.findByText("unauthenticated")).toBeInTheDocument();
    await waitFor(() => expect(handlers.length).toBeGreaterThan(0));
    act(() => handlers.forEach((h) => h({ topic: "push:ag1", type: "delivery", delivery: delivery() })));
    const row = await screen.findByTestId("delivery-d1");
    expect(within(row).getByText("Accepted")).toBeInTheDocument();
    await userEvent.click(within(row).getAllByRole("button")[0]);
    expect(within(row).getByText(/No token received/)).toBeInTheDocument();
    expect(row.textContent).toContain('"taskId": "t1"');
  });

  it("warns when the card does not declare push notifications", async () => {
    setup({ ...agent, card: { capabilities: {} } } as never);
    expect(await screen.findByText(/does not declare push notifications/i)).toBeInTheDocument();
  });
});

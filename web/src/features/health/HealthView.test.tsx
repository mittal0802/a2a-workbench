import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import type { HealthResult, HealthRun } from "../../lib/types";
import { HealthPage, latestByAgent } from "./HealthPage";
import { HealthView, gaugeBackground, headline } from "./HealthView";

const handlers: ((m: Record<string, unknown>) => void)[] = [];
vi.mock("../../lib/ws", () => ({
  getHub: () => ({
    subscribe: (_t: string, _s: number, h: (m: Record<string, unknown>) => void) => {
      handlers.push(h);
      return () => {};
    },
  }),
}));

const result = (over: Partial<HealthResult> = {}): HealthResult => ({
  check_id: "F2.get_unknown", area: "F", title: "Unknown task ids are not found", spec_ref: "A2A §3.1.3",
  level: "must", interface: "http://z/a2a", status: "fail", expected: "TaskNotFoundError",
  actual: "a task (completed)", fix_hint: "Return TaskNotFoundError.", exchange_ids: ["e1"], duration_ms: 3, ...over,
});
const run = (over: Partial<HealthRun> = {}): HealthRun => ({
  id: "r1", agent_id: "ag1", conversation_id: "c1", status: "done", card_url: "http://z/.well-known/agent-card.json",
  areas: ["A", "F"], interfaces: ["http://z/a2a"], score: 75, counts: { pass: 2, warn: 1, fail: 1, not_supported: 1 },
  results: [
    result(),
    result({ check_id: "C7.history_zero", area: "C", title: "History is omitted", level: "should", status: "warn", exchange_ids: [] }),
    result({ check_id: "A1.card_reachable", area: "A", title: "Card is served", status: "pass" }),
    result({ check_id: "G1.stream_capability", area: "G", status: "not_supported", actual: "the card declares streaming" }),
    result({ check_id: "L1.resilience_resubscribe", area: "L", status: "error", actual: "RuntimeError: boom" }),
  ],
  started_at: "2026-10-10T10:00:00Z", finished_at: "2026-10-10T10:01:00Z", ...over,
});
const agent = { id: "ag1", name: "Zoo", card: {} };
const catalogue = {
  areas: { A: "Discovery", C: "Messaging", F: "Task operations", G: "Streaming", L: "Resilience" },
  checks: [{ id: "A1.card_reachable", area: "A", title: "", spec_ref: "", level: "must", fix_hint: "" }],
};

function setup() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <HealthView agent={agent as never} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  handlers.length = 0;
  vi.restoreAllMocks();
  vi.spyOn(api, "healthChecks").mockResolvedValue(catalogue as never);
});

describe("HealthView", () => {
  it("says why it can't start when the check list fails to load", async () => {
    vi.spyOn(api, "healthChecks").mockRejectedValue(new Error("not found"));
    vi.spyOn(api, "listHealthRuns").mockResolvedValue([]);
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <HealthView agent={agent as never} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/couldn't load the list of checks: not found/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check health" })).toBeDisabled();
  });

  it("shows the score, findings with fix and spec ref, and opens evidence", async () => {
    vi.spyOn(api, "listHealthRuns").mockResolvedValue([run()]);
    vi.spyOn(api, "getHealthRun").mockResolvedValue(run());
    const ex = vi.spyOn(api, "getExchange").mockResolvedValue({
      id: "e1", operation: "get_task", http_method: "POST", url: "http://z/a2a", started_at: "", status: 200,
      duration_ms: 4, error: null, frame_count: 0, request_headers: {}, request_body: '{"method":"GetTask"}',
      response_headers: {}, response_body: '{"result":{"id":"x"}}', frames: [], truncated: false, checks: [],
    } as never);
    setup();
    expect(await screen.findByTestId("score")).toHaveTextContent("75");
    expect(screen.getByText("1 rule broken, 1 suggestion")).toBeInTheDocument();
    const issue = screen.getByTestId("issue-F2.get_unknown");
    expect(issue).toHaveTextContent("Return TaskNotFoundError.");
    expect(issue).toHaveTextContent("A2A §3.1.3 · MUST");
    expect(screen.getByTestId("issue-C7.history_zero")).toHaveTextContent("SHOULD");
    expect(screen.getByText("Checks that could not run (not counted)")).toBeInTheDocument();
    expect(screen.getByTestId("area-F")).toHaveTextContent("0/1");
    expect(screen.getByRole("link", { name: "Download JSON" })).toHaveAttribute("href", "/api/health/runs/r1/report.json");
    await userEvent.click(screen.getAllByRole("button", { name: "See evidence" })[0]);
    expect(ex).toHaveBeenCalledWith("e1");
    expect(await screen.findByTestId("evidence")).toHaveTextContent("GetTask");
  });

  it("starts a run for the chosen areas and follows it live", async () => {
    vi.spyOn(api, "listHealthRuns").mockResolvedValue([]);
    const start = vi.spyOn(api, "startHealthRun").mockResolvedValue({ run_id: "r2", topic: "health-run:r2" });
    const get = vi.spyOn(api, "getHealthRun").mockResolvedValue(run({ id: "r2", status: "running", results: [], counts: {}, score: null }));
    setup();
    expect(await screen.findByText(/No health check has run/)).toBeInTheDocument();
    expect(screen.getByText(/create tasks, cancel the tasks they created/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "G · Streaming" }));
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Check health" }));
    expect(start).toHaveBeenCalledWith("ag1", { areas: ["A", "C", "F", "L"], interfaces: "all" });
    expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument();
    await waitFor(() => expect(handlers.length).toBeGreaterThan(0));
    get.mockResolvedValue(run({ id: "r2" }));
    act(() => handlers[0]({ type: "progress", event: { kind: "finished" } }));
    await waitFor(() => expect(screen.getByTestId("score")).toHaveTextContent("75"));
  });

  it("stops a running check", async () => {
    vi.spyOn(api, "listHealthRuns").mockResolvedValue([run({ status: "running" })]);
    vi.spyOn(api, "getHealthRun").mockResolvedValue(run({ status: "running" }));
    const stop = vi.spyOn(api, "stopHealthRun").mockResolvedValue(undefined);
    setup();
    await userEvent.click(await screen.findByRole("button", { name: "Stop" }));
    expect(stop).toHaveBeenCalledWith("r1");
  });

  it("keeps polling a running check even if the finished event was missed", async () => {
    vi.spyOn(api, "listHealthRuns").mockResolvedValue([run({ status: "running" })]);
    const get = vi.spyOn(api, "getHealthRun").mockResolvedValue(run({ status: "running", score: null }));
    setup();
    await screen.findByRole("button", { name: "Stop" });
    get.mockResolvedValue(run());
    await waitFor(() => expect(screen.getByTestId("score")).toHaveTextContent("75"), { timeout: 4000 });
  });

  it("summarizes runs", () => {
    expect(headline(run({ counts: { not_supported: 4, error: 1 } }))).toBe("Nothing could be checked");
    expect(headline(run({ status: "stopped", counts: { pass: 3 } }))).toBe("Stopped early: every check run so far passed");
    expect(headline(run({ counts: { pass: 3 } }))).toBe("Healthy: every applicable check passed");
    expect(headline(run({ counts: { pass: 3, warn: 2 } }))).toBe("Healthy, with 2 suggestions");
    expect(gaugeBackground({ pass: 1, fail: 1 })).toBe(
      "conic-gradient(var(--green) 0% 50%,var(--amber) 50% 50%,var(--red) 50% 100%,var(--line2) 100% 100%)",
    );
    expect(gaugeBackground({})).toBe("var(--line)");
  });
});

describe("HealthPage", () => {
  it("lists the latest run of each agent", async () => {
    vi.spyOn(api, "listAgents").mockResolvedValue([
      { id: "ag1", name: "Zoo" },
      { id: "ag2", name: "Other" },
    ] as never);
    vi.spyOn(api, "listHealthRuns").mockResolvedValue([run({ score: 90 }), run({ id: "old", score: 10 })]);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <HealthPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("health-ag1")).toHaveTextContent("90");
    expect(screen.getByTestId("health-ag1")).toHaveAttribute("href", "/agents/ag1/health");
    expect(screen.getByTestId("health-ag2")).toHaveTextContent("Not checked yet");
    expect(latestByAgent([run({ id: "a" }), run({ id: "b" })]).get("ag1")?.id).toBe("a");
  });
});

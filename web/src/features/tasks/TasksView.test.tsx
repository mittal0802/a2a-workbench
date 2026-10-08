import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { TasksView } from "./TasksView";

const task = (id: string, state: string, text: string) => ({
  id,
  contextId: "ctx",
  state,
  status: { state: `TASK_STATE_${state.toUpperCase()}`, timestamp: "2026-10-08T07:00:00Z" },
  history: [{ role: "ROLE_USER", parts: [{ text }] }],
  artifacts: [{ artifactId: "a", name: "answer", parts: [{ text: `result of ${text}` }] }],
});

const agent = { id: "ag", name: "Zoo", card: {} } as never;

function setup() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TasksView agent={agent} />
    </QueryClientProvider>,
  );
}

describe("TasksView", () => {
  it("lists tasks in plain language and pages with next_page_token", async () => {
    const list = vi
      .spyOn(api, "listTasks")
      .mockResolvedValueOnce({ tasks: [task("t1", "working", "first")], next_page_token: "p2", page_size: 1, total_size: 2 })
      .mockResolvedValueOnce({ tasks: [task("t2", "completed", "second")], next_page_token: null, page_size: 1, total_size: 2 });
    setup();
    expect(await screen.findByText("first")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("Working")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 tasks/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /load more/i }));
    expect(await screen.findByText("second")).toBeInTheDocument();
    expect(list.mock.calls[1][1]).toMatchObject({ page_token: "p2" });
    expect(screen.queryByRole("button", { name: /load more/i })).toBeNull();
  });

  it("refetches with filters", async () => {
    const list = vi.spyOn(api, "listTasks").mockResolvedValue({ tasks: [], next_page_token: null, page_size: 20, total_size: 0 });
    setup();
    await screen.findByText(/no tasks/i);
    await userEvent.selectOptions(screen.getByLabelText(/status/i), "completed");
    await userEvent.click(screen.getByRole("switch", { name: /include results/i }));
    expect(list.mock.lastCall?.[1]).toMatchObject({ status: "completed", include_artifacts: true });
  });

  it("opens a task, shows its history and results, and stops running ones", async () => {
    vi.spyOn(api, "listTasks").mockResolvedValue({ tasks: [task("t1", "working", "first")], next_page_token: null, page_size: 20, total_size: 1 });
    const cancel = vi.spyOn(api, "cancelTask").mockResolvedValue(task("t1", "canceled", "first") as never);
    setup();
    const row = (await screen.findByText("first")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: /open/i }));
    expect(screen.getByText("result of first")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: /stop/i }));
    expect(cancel).toHaveBeenCalledWith("ag", "t1");
  });

  it("finds a task by id", async () => {
    vi.spyOn(api, "listTasks").mockResolvedValue({ tasks: [], next_page_token: null, page_size: 20, total_size: 0 });
    const get = vi.spyOn(api, "getTask").mockResolvedValue(task("tz", "completed", "found it") as never);
    setup();
    await userEvent.type(screen.getByLabelText(/find task by id/i), "tz{Enter}");
    expect(get).toHaveBeenCalledWith("ag", "tz");
    expect(await screen.findByText("result of found it")).toBeInTheDocument();
  });
});

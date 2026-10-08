import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { StatePill } from "../../components/StatusPill";
import { Switch } from "../../components/Switch";
import { api } from "../../lib/api";
import { RUNNING, stateLabel } from "../../lib/labels";
import type { A2ATask, Agent, TaskFilter } from "../../lib/types";
import { TaskDetail } from "./TaskDetail";

const STATES = ["submitted", "working", "input_required", "auth_required", "completed", "failed", "canceled", "rejected"];

function titleOf(t: A2ATask): string {
  for (const m of t.history ?? [])
    if (m.role === "ROLE_USER") for (const p of m.parts) if (p.text) return p.text;
  return t.id;
}

function ago(ts?: string): string {
  if (!ts) return "—";
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(ts).toLocaleString();
}

/** All tasks of an agent (ListTasks) with every filter, pagination, details and stop. */
export function TasksView({ agent }: { agent: Agent }) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<TaskFilter>({ page_size: 20, history_length: 5 });
  const [extra, setExtra] = useState<A2ATask[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [open, setOpen] = useState<A2ATask | null>(null);
  const [findId, setFindId] = useState("");

  const first = useQuery({
    queryKey: ["tasks", agent.id, filter],
    queryFn: async () => {
      const page = await api.listTasks(agent.id, filter);
      setExtra([]);
      setNext(page.next_page_token);
      return page;
    },
  });
  const more = useMutation({
    mutationFn: () => api.listTasks(agent.id, { ...filter, page_token: next ?? undefined }),
    onSuccess: (page) => {
      setExtra((e) => [...e, ...page.tasks]);
      setNext(page.next_page_token);
    },
  });
  const stop = useMutation({
    mutationFn: (taskId: string) => api.cancelTask(agent.id, taskId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", agent.id] }),
  });
  const find = useMutation({ mutationFn: (id: string) => api.getTask(agent.id, id), onSuccess: setOpen });

  const tasks = [...(first.data?.tasks ?? []), ...extra];
  const set = (patch: Partial<TaskFilter>) => setFilter((f) => ({ ...f, ...patch }));

  return (
    <section className="page">
      <div className="wrap">
        <div className="ph">
          <div>
            <h2>Tasks</h2>
            <p>Everything this agent reports through ListTasks</p>
          </div>
          <div className="spacer" />
          <form
            className="search"
            onSubmit={(e) => {
              e.preventDefault();
              if (findId.trim()) find.mutate(findId.trim());
            }}
          >
            ⌕
            <input
              aria-label="Find task by id"
              placeholder="Find task by ID"
              value={findId}
              onChange={(e) => setFindId(e.target.value)}
              style={{ border: 0, outline: 0, background: "none", flex: 1 }}
            />
          </form>
        </div>
        <div className="fbar">
          <label className="filter">
            Status
            <select
              aria-label="Status"
              value={filter.status ?? ""}
              onChange={(e) => set({ status: e.target.value || undefined })}
              style={{ border: 0, background: "none", fontWeight: 500, color: "var(--text)" }}
            >
              <option value="">All</option>
              {STATES.map((s) => (
                <option key={s} value={s}>
                  {stateLabel(s).label}
                </option>
              ))}
            </select>
          </label>
          <label className="filter">
            Conversation
            <input
              aria-label="Context id"
              placeholder="context id"
              value={filter.context_id ?? ""}
              onChange={(e) => set({ context_id: e.target.value || undefined })}
              style={{ border: 0, outline: 0, background: "none", width: 120 }}
            />
          </label>
          <label className="filter">
            Updated after
            <input
              aria-label="Updated after"
              type="datetime-local"
              onChange={(e) => set({ status_timestamp_after: e.target.value ? new Date(e.target.value).toISOString() : undefined })}
              style={{ border: 0, outline: 0, background: "none" }}
            />
          </label>
          <span className="filter">
            Include results
            <Switch
              label="Include results"
              checked={!!filter.include_artifacts}
              onCheckedChange={(v) => set({ include_artifacts: v })}
            />
          </span>
          <label className="filter">
            History
            <input
              aria-label="History length"
              type="number"
              min={0}
              value={filter.history_length ?? ""}
              onChange={(e) => set({ history_length: e.target.value === "" ? undefined : Number(e.target.value) })}
              style={{ border: 0, outline: 0, background: "none", width: 44 }}
            />
          </label>
          <label className="filter">
            Per page
            <select
              aria-label="Page size"
              value={filter.page_size}
              onChange={(e) => set({ page_size: Number(e.target.value) })}
              style={{ border: 0, background: "none" }}
            >
              {[10, 20, 50, 100].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <div className="spacer" />
          <span className="no" style={{ fontSize: 12.5 }}>
            {tasks.length} of {first.data?.total_size ?? "?"} tasks
          </span>
        </div>
        {(first.isError || find.isError || stop.isError) && (
          <div className="err">{((first.error ?? find.error ?? stop.error) as Error).message}</div>
        )}
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>Task</th>
                <th>Status</th>
                <th>Results</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id}>
                  <td>
                    {titleOf(t)}
                    <div className="no mono">{t.id}</div>
                  </td>
                  <td>
                    <StatePill state={t.state} />
                  </td>
                  <td>{t.artifacts?.length ?? "—"}</td>
                  <td className="no">{ago(t.status?.timestamp)}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button className="btn ghost" onClick={() => setOpen(t)}>
                      Open
                    </button>
                    {RUNNING.has(t.state) && (
                      <button className="btn ghost" style={{ color: "var(--red)" }} onClick={() => stop.mutate(t.id)}>
                        Stop
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {first.isSuccess && tasks.length === 0 && (
                <tr>
                  <td colSpan={5} className="no">
                    No tasks match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {next && (
          <div style={{ display: "flex", justifyContent: "center", marginTop: 14 }}>
            <button className="btn" onClick={() => more.mutate()} disabled={more.isPending}>
              {more.isPending ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
        {open && <TaskDetail task={open} onClose={() => setOpen(null)} />}
      </div>
    </section>
  );
}

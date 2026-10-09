import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ConfirmButton } from "../../components/ConfirmButton";
import { JsonView } from "../../components/JsonView";
import { api } from "../../lib/api";
import { stateLabel, toneClass } from "../../lib/labels";
import type { Agent, NewPushConfig, PushDelivery } from "../../lib/types";
import { getHub } from "../../lib/ws";

const REASONS: Record<string, string> = {
  unauthenticated: "Authorization header missing or wrong (A2A §4.3.3, §13.2)",
  wrong_token: "Token does not match the config",
  malformed: "Body is not an A2A StreamResponse",
  unexpected_task: "Notification for a task this webhook was not created for (A2A §4.3.3)",
};

function DeliveryRow({ d }: { d: PushDelivery }) {
  const [open, setOpen] = useState(false);
  const state = d.state ? stateLabel(d.state) : null;
  return (
    <div className={`step ${open ? "open" : ""}`} data-testid={`delivery-${d.id}`}>
      <button className="step-h" style={{ width: "100%", textAlign: "left" }} onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className={`state ${d.verdict === "accepted" ? "s-ok" : "s-bad"}`}>
          <i />
          {d.verdict === "accepted" ? "Accepted" : "Rejected"}
        </span>
        <div>
          {d.kind ?? "notification"}
          {state && <span className={`state ${toneClass(state.tone)}`} style={{ marginLeft: 6 }}>{state.label}</span>}
          {d.duplicate && <span className="tag" style={{ marginLeft: 6 }}>duplicate</span>}
          {d.reasons.map((r) => (
            <span key={r} className="tag" style={{ marginLeft: 6, color: "var(--red)" }} title={REASONS[r]}>
              {r}
            </span>
          ))}
          <br />
          <small>
            {new Date(d.received_at).toLocaleTimeString()}
            {d.task_id ? ` · task ${d.task_id}` : ""}
          </small>
        </div>
      </button>
      <div className="step-b">
        {d.reasons.map((r) => (
          <div key={r} className="err">
            {REASONS[r] ?? r}
          </div>
        ))}
        {d.notes.map((n, i) => (
          <div key={i} className="no">
            {n}
          </div>
        ))}
        <table className="table" style={{ fontSize: 12, margin: "6px 0" }}>
          <tbody>
            {Object.entries(d.headers).map(([k, v]) => (
              <tr key={k}>
                <td className="mono" style={{ padding: "3px 8px", color: "var(--muted)" }}>
                  {k}
                </td>
                <td className="mono" style={{ padding: "3px 8px", wordBreak: "break-all" }}>
                  {v}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {d.payload && <JsonView value={d.payload} />}
      </div>
    </div>
  );
}

/** Push notifications for one agent: configs per task (A2A §3.1.7–§3.1.10) and the delivery inbox. */
export function NotificationsView({ agent }: { agent: Agent }) {
  const qc = useQueryClient();
  const declared = !!agent.card.capabilities?.pushNotifications;
  const tasks = useQuery({ queryKey: ["tasks", agent.id, "push"], queryFn: () => api.listTasks(agent.id, { page_size: 50 }) });
  const publicUrl = useQuery({ queryKey: ["public-url"], queryFn: api.publicUrl });
  const [taskId, setTaskId] = useState("");
  const [mode, setMode] = useState<"workbench" | "custom">("workbench");
  const [custom, setCustom] = useState({ url: "", token: "", auth_scheme: "Bearer", auth_credentials: "" });
  const configs = useQuery({
    queryKey: ["push-configs", agent.id, taskId],
    queryFn: () => api.listPushConfigs(agent.id, taskId),
    enabled: !!taskId,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["push-configs", agent.id, taskId] });
  const create = useMutation({
    mutationFn: () => {
      const body: NewPushConfig =
        mode === "workbench"
          ? { webhook: "workbench" }
          : {
              webhook: "custom",
              url: custom.url,
              ...(custom.token ? { token: custom.token } : {}),
              ...(custom.auth_credentials ? { auth_scheme: custom.auth_scheme, auth_credentials: custom.auth_credentials } : {}),
            };
      return api.createPushConfig(agent.id, taskId, body);
    },
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: (id: string) => api.deletePushConfig(agent.id, taskId, id), onSuccess: refresh });

  const fetched = useQuery({ queryKey: ["push-deliveries", agent.id], queryFn: () => api.pushDeliveries(agent.id) });
  const [live, setLive] = useState<PushDelivery[]>([]);
  useEffect(() => {
    setLive([]);
    return getHub().subscribe(`push:${agent.id}`, 0, (msg) => {
      if (msg.type === "delivery") setLive((prev) => [msg.delivery as PushDelivery, ...prev]);
    });
  }, [agent.id]);
  const seen = new Set<string>();
  const deliveries = [...live, ...(fetched.data ?? [])].filter((d) => (seen.has(d.id) ? false : (seen.add(d.id), true)));
  const local = publicUrl.data?.source === "local";

  return (
    <section className="page">
      <div className="wrap">
        <div className="ph">
          <div>
            <h2>Notifications</h2>
            <p>Push notification configs for a task, and every notification the agent sent to a Workbench webhook</p>
          </div>
        </div>
        {!declared && (
          <div className="note warn" style={{ marginBottom: 14 }}>
            <span className="i">!</span>
            <div>
              This agent's card does not declare push notifications. Its config calls should answer PushNotificationNotSupportedError
              (A2A §3.3.4); you can still send them to check.
            </div>
          </div>
        )}
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-h">
            <h3 style={{ fontSize: 14, fontWeight: 600 }}>Configs</h3>
          </div>
          <div className="card-b">
            <label className="lbl2" style={{ display: "block", fontSize: 12.5 }}>
              Task
              <select className="jsonedit" style={{ minHeight: 0 }} value={taskId} onChange={(e) => setTaskId(e.target.value)}>
                <option value="">Choose a task…</option>
                {(tasks.data?.tasks ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.id} · {stateLabel((t as { state?: string }).state ?? "unspecified").label}
                  </option>
                ))}
              </select>
            </label>
            {taskId && (
              <>
                {(configs.data?.configs ?? []).map((c) => (
                  <div className="row" key={c.id}>
                    <span className="mono" style={{ flex: "none" }}>{c.id}</span>
                    <span className="mono no" style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {c.url}
                    </span>
                    {c.authentication?.scheme && <span className="tag">{c.authentication.scheme}</span>}
                    <ConfirmButton label={`Delete config ${c.id}`} question="Delete?" onConfirm={() => remove.mutate(c.id)}>
                      ✕
                    </ConfirmButton>
                  </div>
                ))}
                {configs.data && configs.data.configs.length === 0 && <p className="no">No configs for this task yet.</p>}
                <form
                  style={{ marginTop: 12 }}
                  onSubmit={(e) => {
                    e.preventDefault();
                    create.mutate();
                  }}
                >
                  <label className="choice" style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
                    <input type="radio" name="webhook" checked={mode === "workbench"} onChange={() => setMode("workbench")} aria-label="Workbench webhook" />
                    <span>
                      Workbench webhook
                      <small className="no" style={{ display: "block" }}>
                        A new URL under {publicUrl.data?.public_base_url ?? "…"} with its own token and Bearer credential.
                        {local && " The agent must be able to reach this address; for remote agents set a public URL or start a tunnel in Settings."}
                      </small>
                    </span>
                  </label>
                  <label className="choice" style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, marginTop: 6 }}>
                    <input type="radio" name="webhook" checked={mode === "custom"} onChange={() => setMode("custom")} aria-label="My own webhook" />
                    My own webhook
                  </label>
                  {mode === "custom" && (
                    <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
                      <label className="lbl2" style={{ fontSize: 12.5 }}>
                        Webhook URL
                        <input className="jsonedit" style={{ minHeight: 0 }} value={custom.url} onChange={(e) => setCustom({ ...custom, url: e.target.value })} />
                      </label>
                      <label className="lbl2" style={{ fontSize: 12.5 }}>
                        Token
                        <input className="jsonedit" style={{ minHeight: 0 }} type="password" value={custom.token} onChange={(e) => setCustom({ ...custom, token: e.target.value })} />
                      </label>
                      <label className="lbl2" style={{ fontSize: 12.5 }}>
                        Auth scheme and credentials
                        <span style={{ display: "flex", gap: 6 }}>
                          <input className="jsonedit" style={{ minHeight: 0, width: 110 }} aria-label="Auth scheme" value={custom.auth_scheme} onChange={(e) => setCustom({ ...custom, auth_scheme: e.target.value })} />
                          <input className="jsonedit" style={{ minHeight: 0, flex: 1 }} type="password" aria-label="Credentials" value={custom.auth_credentials} onChange={(e) => setCustom({ ...custom, auth_credentials: e.target.value })} />
                        </span>
                      </label>
                    </div>
                  )}
                  <button className="btn primary" style={{ marginTop: 10 }} disabled={create.isPending || (mode === "custom" && !custom.url)}>
                    Create config
                  </button>
                  {(create.isError || remove.isError || configs.isError) && (
                    <div className="err">{((create.error ?? remove.error ?? configs.error) as Error).message}</div>
                  )}
                </form>
              </>
            )}
          </div>
        </div>
        <div className="card">
          <div className="card-h">
            <h3 style={{ fontSize: 14, fontWeight: 600 }}>Deliveries</h3>
            <span className="spacer" />
            <span className="no" style={{ fontSize: 12 }}>
              {deliveries.length} received
            </span>
          </div>
          <div className="card-b">
            {deliveries.length === 0 && <p className="no">Nothing yet. Notifications to Workbench webhooks show up here as they arrive.</p>}
            {deliveries.map((d) => (
              <DeliveryRow key={d.id} d={d} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

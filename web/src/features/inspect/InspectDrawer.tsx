import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { CopyButton, downloadText } from "../../components/CopyButton";
import { JsonView } from "../../components/JsonView";
import { api } from "../../lib/api";
import type { ExchangeRecord, ExchangeSummary } from "../../lib/types";
import { getHub } from "../../lib/ws";

const OPERATIONS: Record<string, string> = {
  get_agent_card: "Fetch agent card",
  send_message: "Send message",
  cancel_task: "Stop task",
};

/** Plain-language name of a recorded exchange. */
export function friendlyOperation(ex: Pick<ExchangeSummary, "operation" | "frame_count" | "http_method" | "url">): string {
  const base = OPERATIONS[ex.operation];
  if (!base) {
    let path = ex.url;
    try {
      path = new URL(ex.url).pathname;
    } catch {
      /* keep the raw URL */
    }
    return `${ex.http_method} ${path}`;
  }
  return ex.operation === "send_message" && ex.frame_count > 0 ? `${base} (stream)` : base;
}

const quote = (s: string) => `'${s.replace(/'/g, "'\\''")}'`;

/** A curl command reproducing the recorded request (redacted headers stay redacted). */
export function curlFor(ex: ExchangeRecord): string {
  const parts = [`curl -X ${ex.http_method} ${quote(ex.url)}`];
  for (const [k, v] of Object.entries(ex.request_headers)) {
    if (["host", "content-length", "accept-encoding", "connection", "user-agent"].includes(k)) continue;
    parts.push(`-H ${quote(`${k}: ${v}`)}`);
  }
  if (ex.request_body) parts.push(`--data ${quote(ex.request_body)}`);
  return parts.join(" \\\n  ");
}

function parsed(text: string | null): unknown {
  if (text === null) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export type ExchangeExport = {
  id: string;
  operation: string;
  started_at: string;
  duration_ms: number | null;
  error: string | null;
  fault?: string;
  request: { method: string; url: string; headers: Record<string, string>; body: unknown };
  response: {
    status: number | null;
    headers: Record<string, string>;
    body?: unknown;
    events?: { t_ms: number; data: unknown }[];
    truncated?: boolean;
  };
};

/** A recorded exchange as a portable JSON document: JSON bodies parsed, stream events listed in order. */
export function exchangeExport(ex: ExchangeRecord): ExchangeExport {
  return {
    id: ex.id,
    operation: ex.operation,
    started_at: ex.started_at,
    duration_ms: ex.duration_ms,
    error: ex.error,
    ...(ex.fault ? { fault: ex.fault } : {}),
    request: { method: ex.http_method, url: ex.url, headers: ex.request_headers, body: parsed(ex.request_body) },
    response: {
      status: ex.status,
      headers: ex.response_headers,
      ...(ex.frames.length > 0
        ? { events: ex.frames.map((f) => ({ t_ms: f.t_ms, data: parsed(frameData(f.data) || f.data) })) }
        : { body: parsed(ex.response_body) }),
      ...(ex.truncated ? { truncated: true } : {}),
    },
  };
}

const pretty = (v: unknown) => JSON.stringify(v, null, 2);

function frameData(frame: string): string {
  return frame
    .split("\n")
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).trimStart())
    .join("\n");
}

function Headers({ title, headers }: { title: string; headers: Record<string, string> }) {
  return (
    <>
      <h5 className="no" style={{ margin: "10px 0 4px", fontSize: 12 }}>
        {title}
      </h5>
      <table className="table" style={{ fontSize: 12 }}>
        <tbody>
          {Object.entries(headers).map(([k, v]) => (
            <tr key={k}>
              <td className="mono" style={{ padding: "4px 8px", color: "var(--muted)" }}>
                {k}
              </td>
              <td className="mono" style={{ padding: "4px 8px", wordBreak: "break-all" }}>
                {v}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Detail({ id }: { id: string }) {
  const [view, setView] = useState<"Request" | "Response" | "Headers">("Request");
  const ex = useQuery({ queryKey: ["exchange", id], queryFn: () => api.getExchange(id), retry: false });
  if (ex.isError)
    return (
      <div className="dbody no">
        This request is not recorded yet. It appears here as soon as the agent answers.{" "}
        <button className="try" onClick={() => ex.refetch()}>
          Retry
        </button>
      </div>
    );
  if (!ex.data) return <div className="dbody no">Loading…</div>;
  const r = ex.data;
  return (
    <div className="dbody">
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
        <div className="seg">
          {(["Request", "Response", "Headers"] as const).map((v) => (
            <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)}>
              {v}
            </button>
          ))}
        </div>
        <div className="spacer" />
        <CopyButton text={() => pretty(exchangeExport(r))} label="Copy exchange" />
        <button className="ib" onClick={() => downloadText(`exchange-${r.id}.json`, pretty(exchangeExport(r)))}>
          Download
        </button>
        <CopyButton text={() => curlFor(r)} label="Copy as cURL" />
      </div>
      <div className="mono" style={{ marginBottom: 8, wordBreak: "break-all" }}>
        {r.http_method} {r.url} → {r.status ?? "no response"} ·{" "}
        {r.complete === false ? "in progress" : `${r.duration_ms ?? "?"} ms`}
      </div>
      {r.error && (
        <div className="note bad">
          <span className="i">✕</span>
          <div>{r.error}</div>
        </div>
      )}
      {view === "Request" && (r.request_body ? <JsonView raw={r.request_body} /> : <div className="no">No request body.</div>)}
      {view === "Response" &&
        (r.frames.length > 0 ? (
          r.frames.map((f, i) => (
            <div key={i} style={{ marginBottom: 8 }}>
              <div className="no mono" style={{ fontSize: 11.5 }}>
                +{f.t_ms} ms · event {i + 1}
              </div>
              <JsonView raw={frameData(f.data) || f.data} />
            </div>
          ))
        ) : r.response_body ? (
          <>
            <JsonView raw={r.response_body} />
            {r.truncated && <div className="no">Body truncated.</div>}
          </>
        ) : (
          <div className="no">No response body.</div>
        ))}
      {view === "Headers" && (
        <>
          <Headers title="Request headers" headers={r.request_headers} />
          <Headers title="Response headers" headers={r.response_headers} />
        </>
      )}
    </div>
  );
}

/** Side drawer listing every exchange of a conversation with its full wire detail. */
export function InspectDrawer({
  conversationId,
  open,
  onClose,
  focusExchangeId,
}: {
  conversationId: string | null;
  open: boolean;
  onClose: () => void;
  focusExchangeId?: string;
}) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(focusExchangeId ?? null);
  const [exporting, setExporting] = useState(false);
  useEffect(() => {
    if (focusExchangeId) setSelected(focusExchangeId);
  }, [focusExchangeId]);
  const list = useQuery({
    queryKey: ["exchanges", conversationId],
    queryFn: () => api.listExchanges(conversationId!),
    enabled: !!conversationId && open,
  });
  useEffect(() => {
    if (!conversationId || !open) return;
    return getHub().subscribe(`exchanges:${conversationId}`, 0, (msg) => {
      if (msg.type !== "exchange") return;
      const incoming = msg.exchange as ExchangeSummary;
      qc.setQueryData<ExchangeSummary[]>(["exchanges", conversationId], (prev = []) =>
        prev.some((e) => e.id === incoming.id)
          ? prev.map((e) => (e.id === incoming.id ? incoming : e))
          : [...prev, incoming],
      );
      qc.invalidateQueries({ queryKey: ["exchange", incoming.id] });
    });
  }, [conversationId, open, qc]);

  return (
    <aside className={`drawer ${open ? "on" : ""}`} aria-hidden={!open} aria-label="Inspect">
      <div className="drawer-in">
        <div className="dh">
          <b>Inspect</b>
          <span className="no" style={{ fontSize: 12 }}>
            {list.data?.length ?? 0} requests
          </span>
          <div className="spacer" />
          {conversationId && (list.data?.length ?? 0) > 0 && (
            <button
              className="ib"
              disabled={exporting}
              onClick={async () => {
                setExporting(true);
                try {
                  const records = await Promise.all(list.data!.map((e) => api.getExchange(e.id)));
                  const doc = {
                    conversation_id: conversationId,
                    exported_at: new Date().toISOString(),
                    exchanges: records.map(exchangeExport),
                  };
                  downloadText(`conversation-${conversationId}-exchanges.json`, pretty(doc));
                } finally {
                  setExporting(false);
                }
              }}
            >
              {exporting ? "Exporting…" : "Export all"}
            </button>
          )}
          <button className="ib" onClick={onClose} aria-label="Close inspect">
            ✕
          </button>
        </div>
        <div className="calls">
          {!conversationId && <div className="no" style={{ padding: 10 }}>Send a message to see its traffic.</div>}
          {list.data?.map((e) => (
            <button
              key={e.id}
              className={`call ${selected === e.id ? "sel" : ""}`}
              style={{ width: "100%", textAlign: "left" }}
              onClick={() => setSelected(e.id)}
            >
              <span className={`d ${e.error ? "" : "out"}`} style={e.error ? { color: "var(--red)" } : undefined}>
                {e.error ? "✕" : "↑"}
              </span>
              {friendlyOperation(e)}
              {e.fault && (
                <span className="tag" style={{ marginLeft: 6, background: "var(--amber-soft)", color: "var(--amber)" }}>
                  injected: {e.fault}
                </span>
              )}
              {e.error && <small style={{ marginLeft: 6 }}>{e.error}</small>}
              <span className="ms">
                {e.status ?? "—"} ·{" "}
                {e.complete === false ? "in progress" : e.duration_ms !== null ? `${Math.round(e.duration_ms)}ms` : "…"}
              </span>
            </button>
          ))}
        </div>
        {selected && <Detail id={selected} />}
      </div>
    </aside>
  );
}

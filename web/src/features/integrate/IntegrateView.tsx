import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CopyButton, downloadText } from "../../components/CopyButton";
import { api } from "../../lib/api";
import type { IntegrationGuide } from "../../lib/types";

const TARGETS: { id: string; label: string }[] = [
  { id: "sdk", label: "Plain a2a-sdk" },
  { id: "adk", label: "Google ADK" },
  { id: "langgraph", label: "LangGraph / LangChain" },
  { id: "openai", label: "OpenAI Agents SDK" },
  { id: "claude", label: "Claude Agent SDK" },
];

/** How to call this agent from your own agent: generated code, guidance and card readiness. */
export function IntegrateView({ agentId }: { agentId: string }) {
  const guide = useQuery({ queryKey: ["integration", agentId], queryFn: () => api.integration(agentId) });
  const [target, setTarget] = useState("sdk");
  if (guide.isError) return <div className="empty">{(guide.error as Error).message}</div>;
  if (!guide.data) return <div className="empty">Loading…</div>;
  const g: IntegrationGuide = guide.data;
  const s = g.snippets[target];
  return (
    <div className="pad" style={{ padding: "18px 24px", maxWidth: 980 }}>
      <div className="card">
        <div className="card-h">
          <h3 style={{ fontSize: 14, fontWeight: 600 }}>Call {g.agent} from your agent</h3>
        </div>
        <div className="card-b">
          <p className="no" style={{ marginBottom: 10, fontSize: 12.5 }}>
            Generated from the agent card at <span className="mono">{g.card_url}</span>. It uses the official a2a-sdk and follows
            the A2A client rules; each rule is commented with its spec section. Secrets come from environment variables.
          </p>
          <div className="seg" role="group" aria-label="Framework" style={{ flexWrap: "wrap" }}>
            {TARGETS.map((t) => (
              <button key={t.id} className={target === t.id ? "on" : ""} onClick={() => setTarget(t.id)}>
                {t.label}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "12px 0 6px" }}>
            <span className="mono" style={{ fontSize: 12 }}>
              {s.install}
            </span>
            <div className="spacer" />
            <CopyButton text={() => s.code} label="Copy code" />
            <button className="ib" onClick={() => downloadText(`call_${g.agent.toLowerCase().replace(/[^a-z0-9]+/g, "_")}.py`, s.code, "text/x-python")}>
              Download
            </button>
          </div>
          <pre className="code" style={{ maxHeight: 520 }}>
            {s.code}
          </pre>
          {Object.keys(s.env).length > 0 && (
            <>
              <h5 className="no" style={{ margin: "12px 0 4px", fontSize: 12 }}>
                Environment variables
              </h5>
              <table className="table" style={{ fontSize: 12 }}>
                <tbody>
                  {Object.entries(s.env).map(([k, v]) => (
                    <tr key={k}>
                      <td className="mono" style={{ padding: "4px 8px" }}>
                        {k}
                      </td>
                      <td style={{ padding: "4px 8px" }}>{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <div className="card-h">
          <h3 style={{ fontSize: 14, fontWeight: 600 }}>Calling it from another agent</h3>
        </div>
        <div className="card-b">
          <ul style={{ paddingLeft: 18, fontSize: 13, lineHeight: 1.55 }}>
            {g.guidance.map((line, i) => (
              <li key={i} style={{ marginBottom: 6 }}>
                {line}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <div className="card-h">
          <h3 style={{ fontSize: 14, fontWeight: 600 }}>Ready for agent callers?</h3>
          <span className="spacer" />
          {g.readiness.length === 0 && (
            <span className="status">
              <i />
              Looks good
            </span>
          )}
        </div>
        <div className="card-b">
          {g.readiness.length === 0 && <p className="no">Every skill has its required fields, examples and media types.</p>}
          {g.readiness.map((f, i) => (
            <div className="row" key={i} style={{ alignItems: "flex-start" }}>
              <span className={`state ${f.level === "spec" ? "s-bad" : "s-warn"}`} style={{ flex: "none" }}>
                {f.level === "spec" ? "Spec issue" : "Advice"}
              </span>
              <span style={{ fontSize: 13 }}>
                {f.message} <span className="mono no">{f.path}</span>
                {f.spec_ref && <div className="no" style={{ fontSize: 12 }}>{f.spec_ref}</div>}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

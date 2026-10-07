import { useState } from "react";
import { JsonView } from "../../components/JsonView";
import { bindingLabel } from "../../lib/labels";
import type { Agent } from "../../lib/types";

const SIGNATURE_TEXT: Record<Agent["signature_status"], string> = {
  verified: "Signature verified",
  invalid: "Signature invalid",
  unsigned: "Card is not signed",
  unverifiable: "Signature can't be checked",
};

function YesNo({ value }: { value: unknown }) {
  return value ? <span className="yes">✓ Yes</span> : <span className="no">No</span>;
}

function list(values: unknown): string {
  return Array.isArray(values) && values.length ? values.join(", ") : "—";
}

/** Everything the agent card declares, in plain language, with the raw card on request. */
export function AboutView({ agent, onTry }: { agent: Agent; onTry: (text: string) => void }) {
  const [raw, setRaw] = useState(false);
  const card = agent.card;
  const caps = card.capabilities ?? {};
  const extensions: { uri: string; description?: string; required?: boolean; params?: unknown }[] =
    caps.extensions ?? [];
  const schemes = Object.entries((card.securitySchemes ?? {}) as Record<string, Record<string, unknown>>);
  return (
    <section className="page">
      <div className="wrap">
        <div className="ph">
          <div>
            <h2>About this agent</h2>
            <p>
              From its public agent card · {SIGNATURE_TEXT[agent.signature_status]}
              {agent.signature_detail ? ` (${agent.signature_detail})` : ""} ·{" "}
              <button className="try" onClick={() => setRaw(!raw)}>
                {raw ? "Hide raw card" : "View raw card"}
              </button>
            </p>
          </div>
        </div>
        {raw && (
          <div style={{ marginBottom: 14 }}>
            <JsonView value={card} />
          </div>
        )}
        <div className="cards" style={{ gridTemplateColumns: "1.2fr 1fr", marginBottom: 14 }}>
          <div className="card">
            <div className="card-h">
              {card.iconUrl && <img src={card.iconUrl} alt="" width={20} height={20} />}
              Overview
            </div>
            <div className="card-b">
              <p style={{ color: "var(--muted)", marginBottom: 8 }}>{card.description}</p>
              <div className="row">
                <span className="l">Made by</span>
                <span>{card.provider?.organization ?? "—"}</span>
              </div>
              <div className="row">
                <span className="l">Version</span>
                <span>{card.version ?? "—"}</span>
              </div>
              <div className="row">
                <span className="l">Understands</span>
                <span>{list(card.defaultInputModes)}</span>
              </div>
              <div className="row">
                <span className="l">Replies with</span>
                <span>{list(card.defaultOutputModes)}</span>
              </div>
              <div className="row">
                <span className="l">Docs</span>
                {card.documentationUrl ? (
                  <a href={card.documentationUrl} target="_blank" rel="noreferrer" style={{ color: "var(--brand)" }}>
                    {card.documentationUrl}
                  </a>
                ) : (
                  <span>—</span>
                )}
              </div>
            </div>
          </div>
          <div className="card">
            <div className="card-h">What it supports</div>
            <div className="card-b">
              <div className="row">
                <span className="l">Live streaming</span>
                <YesNo value={caps.streaming} />
              </div>
              <div className="row">
                <span className="l">Push notifications</span>
                <YesNo value={caps.pushNotifications} />
              </div>
              <div className="row">
                <span className="l">Extra details after sign-in</span>
                <YesNo value={caps.extendedAgentCard} />
              </div>
              <div className="row">
                <span className="l">Extensions</span>
                <span>
                  {extensions.length}
                  <span className="no"> · {extensions.filter((e) => e.required).length} required</span>
                </span>
              </div>
              <div className="row">
                <span className="l">Ways to connect</span>
                <span>{[...new Set(agent.interfaces.map((i) => bindingLabel(i.binding)))].join(", ") || "—"}</span>
              </div>
            </div>
          </div>
        </div>
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-h">
            Skills <small>· what you can ask it to do</small>
          </div>
          <div className="card-b" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {(card.skills ?? []).map((s: Record<string, any>) => (
              <div className="skill" key={s.id}>
                <h4>
                  {s.name}
                  {s.securityRequirements?.length ? (
                    <span className="tag" style={{ marginLeft: 6 }}>
                      sign-in
                    </span>
                  ) : null}
                </h4>
                <p>{s.description}</p>
                {(s.tags ?? []).length > 0 && <p className="no">{s.tags.join(" · ")}</p>}
                {(s.examples ?? []).map((ex: string) => (
                  <div key={ex}>
                    <button className="try" onClick={() => onTry(ex)}>
                      Try: “{ex}” →
                    </button>
                  </div>
                ))}
              </div>
            ))}
            {(card.skills ?? []).length === 0 && <p className="no">This agent lists no skills.</p>}
          </div>
        </div>
        <div className="cards" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div className="card">
            <div className="card-h">Extensions</div>
            <div className="card-b">
              {extensions.map((e) => (
                <div className="row" key={e.uri}>
                  <div>
                    {e.description || "Extension"}
                    {e.required && (
                      <span className="tag" style={{ marginLeft: 6, background: "var(--amber-soft)", color: "var(--amber)" }}>
                        required
                      </span>
                    )}
                    <div className="no mono">{e.uri}</div>
                  </div>
                </div>
              ))}
              {extensions.length === 0 && <p className="no">No extensions declared.</p>}
            </div>
          </div>
          <div className="card">
            <div className="card-h">Sign-in methods</div>
            <div className="card-b">
              {schemes.map(([name, scheme]) => (
                <div className="row" key={name}>
                  <span className="l">{name}</span>
                  <span className="mono">{Object.keys(scheme)[0]?.replace(/SecurityScheme$/, "")}</span>
                </div>
              ))}
              {schemes.length === 0 && <p className="no">No sign-in required.</p>}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

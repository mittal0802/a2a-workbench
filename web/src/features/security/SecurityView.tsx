import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "../../lib/api";
import type { CredentialInput, SchemeOverview, SecurityOverview } from "../../lib/types";
import { OAuthCard } from "./OAuthCard";

/** Where an API key goes, in plain language. */
function keyPlacement(details: Record<string, any>): string {
  const name = details.name ?? "?";
  if (details.location === "query") return `Sent as ?${name}=… in the URL`;
  if (details.location === "cookie") return `Sent in the ${name} cookie`;
  return `Sent in the ${name} header`;
}

function describe(scheme: SchemeOverview): string {
  if (scheme.type === "apiKey") return keyPlacement(scheme.details);
  if (scheme.type === "http") return scheme.label === "Bearer token" ? "Sent as Authorization: Bearer …" : "Sent as Authorization: Basic …";
  if (scheme.type === "mutualTLS") return "Your client certificate is presented when connecting";
  if (scheme.type === "oauth2") return `OAuth 2.0 · ${Object.keys(scheme.details.flows ?? {}).join(", ") || "flows"}`;
  if (scheme.type === "openIdConnect") return `OpenID Connect · ${scheme.details.openIdConnectUrl ?? ""}`;
  return "";
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
      {label}
      <div style={{ marginTop: 4 }}>{children}</div>
    </label>
  );
}

const input = { className: "jsonedit", style: { minHeight: 0 } } as const;

function readFile(file: File): Promise<string> {
  return file.text();
}

function CredentialForm({ scheme, onSave, saving }: { scheme: SchemeOverview; onSave: (c: CredentialInput) => void; saving: boolean }) {
  const [v, setV] = useState<Record<string, string>>({});
  const set = (k: string) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  const kind = scheme.accepts[0];
  let fields: ReactNode;
  if (kind === "api_key")
    fields = (
      <Field label="API key">
        <input {...input} type="password" aria-label="API key" value={v.value ?? ""} onChange={set("value")} />
      </Field>
    );
  else if (kind === "http_basic")
    fields = (
      <>
        <Field label="Username">
          <input {...input} aria-label="Username" value={v.username ?? ""} onChange={set("username")} />
        </Field>
        <Field label="Password">
          <input {...input} type="password" aria-label="Password" value={v.password ?? ""} onChange={set("password")} />
        </Field>
      </>
    );
  else if (kind === "http_bearer")
    fields = (
      <Field label="Token">
        <input {...input} type="password" aria-label="Token" value={v.token ?? ""} onChange={set("token")} />
      </Field>
    );
  else if (kind === "mtls")
    fields = (
      <>
        {(
          [
            ["cert_pem", "Client certificate (PEM)"],
            ["key_pem", "Private key (PEM)"],
            ["ca_pem", "CA to trust (PEM, optional)"],
          ] as const
        ).map(([k, label]) => (
          <Field key={k} label={label}>
            <input
              type="file"
              aria-label={label}
              accept=".pem,.crt,.key,.cer"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) setV((old) => ({ ...old, [k]: "" }));
                if (f) {
                  const text = await readFile(f);
                  setV((old) => ({ ...old, [k]: text }));
                }
              }}
            />
          </Field>
        ))}
      </>
    );
  else
    fields = (
      <Field label="Access token (paste one you already have)">
        <input {...input} type="password" aria-label="Access token" value={v.access_token ?? ""} onChange={set("access_token")} />
      </Field>
    );
  const body = { kind, ...Object.fromEntries(Object.entries(v).filter(([, x]) => x)) } as CredentialInput;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave(body);
      }}
    >
      {fields}
      <button className="btn primary" style={{ marginTop: 10 }} disabled={saving || Object.keys(body).length < 2}>
        {saving ? "Saving…" : "Save"}
      </button>
    </form>
  );
}

function SchemeCard({ agentId, scheme, needed }: { agentId: string; scheme: SchemeOverview; needed: boolean }) {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["security", agentId] });
  };
  const save = useMutation({ mutationFn: (c: CredentialInput) => api.putCredential(agentId, scheme.name, c), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => api.deleteCredential(agentId, scheme.name), onSuccess: refresh });
  const cred = scheme.credential;
  return (
    <div className="card">
      <div className="card-h">
        <h3 style={{ fontSize: 14, fontWeight: 600 }}>{scheme.label}</h3>
        <span className="spacer" />
        {cred ? (
          cred.readable ? (
            <span className="status">
              <i />
              Saved
            </span>
          ) : (
            <span className="state s-bad">Can't be read</span>
          )
        ) : needed ? (
          <span className="state s-warn">Needed</span>
        ) : (
          <span className="tag">Not set</span>
        )}
      </div>
      <div className="card-b">
        <p className="no" style={{ marginBottom: 6 }}>
          {describe(scheme)}
          {scheme.description ? ` · ${scheme.description}` : ""}
          <span className="mono" style={{ marginLeft: 6 }}>({scheme.name})</span>
        </p>
        {cred && (
          <div className="row">
            <span className="mono">{cred.preview}</span>
            <button className="btn ghost" style={{ color: "var(--red)" }} onClick={() => remove.mutate()}>
              Remove
            </button>
          </div>
        )}
        <CredentialForm scheme={scheme} onSave={(c) => save.mutate(c)} saving={save.isPending} />
        {(save.isError || remove.isError) && <div className="err">{((save.error ?? remove.error) as Error).message}</div>}
      </div>
    </div>
  );
}

function requirementText(sec: SecurityOverview): string {
  const label = (n: string) => sec.schemes.find((s) => s.name === n)?.label ?? n;
  const alts = sec.requirements.map((r) => r.map(label).join(" and "));
  return alts.length === 1 ? `This agent needs: ${alts[0]}.` : `This agent accepts any one of: ${alts.join(" · or · ")}.`;
}

const OUTCOME: Record<string, { cls: string; icon: string }> = {
  pass: { cls: "ok", icon: "✓" },
  fail: { cls: "bad", icon: "✕" },
  warn: { cls: "warn", icon: "!" },
  error: { cls: "bad", icon: "?" },
  skipped: { cls: "warn", icon: "–" },
  not_applicable: { cls: "ok", icon: "–" },
};

function Enforcement({ agentId }: { agentId: string }) {
  const run = useMutation({ mutationFn: () => api.probeSecurity(agentId) });
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div className="card-h">
        Is it enforced?
        <small>· harmless GetTask calls without, with wrong, and with your credentials</small>
        <span className="spacer" />
        <button className="btn" onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Checking…" : "Check enforcement"}
        </button>
      </div>
      <div className="card-b">
        {run.isError && <div className="err">{(run.error as Error).message}</div>}
        {run.data?.map((r) => (
          <div key={r.check} className={`note ${OUTCOME[r.outcome]?.cls ?? "warn"}`}>
            <span className="i">{OUTCOME[r.outcome]?.icon ?? "?"}</span>
            <div>
              {r.title}
              <small>{r.detail}</small>
            </div>
            <a>{r.spec_ref}</a>
          </div>
        ))}
        {!run.data && !run.isError && <p className="no">Run the checks to see whether the agent enforces its sign-in.</p>}
      </div>
    </div>
  );
}

/** How the agent asks you to sign in, with a form for every scheme it declares. */
export function SecurityView({ agentId }: { agentId: string }) {
  const sec = useQuery({ queryKey: ["security", agentId], queryFn: () => api.security(agentId) });
  if (!sec.data) return <div className="empty">{sec.isError ? (sec.error as Error).message : "Loading…"}</div>;
  const s = sec.data;
  return (
    <section className="page">
      <div className="wrap">
        <div className="ph">
          <div>
            <h2>Security</h2>
            <p>How this agent asks you to sign in, from its agent card</p>
          </div>
          <div className="spacer" />
          {s.status === "signed_in" && (
            <span className="status">
              <i />
              Signed in
            </span>
          )}
          {s.status === "sign_in_needed" && <span className="state s-warn">Sign-in needed</span>}
        </div>
        {s.status === "not_required" ? (
          <p className="no">This agent doesn't require sign-in.</p>
        ) : (
          <>
            <div className={`note ${s.status === "signed_in" ? "ok" : "warn"}`} style={{ marginBottom: 14 }}>
              <span className="i">{s.status === "signed_in" ? "✓" : "!"}</span>
              <div>
                {requirementText(s)}
                {s.missing.length > 0 && (
                  <small>Still missing: {s.missing.map((n) => s.schemes.find((x) => x.name === n)?.label ?? n).join(", ")}</small>
                )}
              </div>
            </div>
            <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
              {s.schemes.map((scheme) =>
                scheme.type === "oauth2" || scheme.type === "openIdConnect" ? (
                  <OAuthCard
                    key={scheme.name}
                    agentId={agentId}
                    scheme={scheme}
                    requiredScopes={s.required_scopes?.[scheme.name] ?? []}
                    needed={s.missing.includes(scheme.name)}
                  />
                ) : (
                  <SchemeCard key={scheme.name} agentId={agentId} scheme={scheme} needed={s.missing.includes(scheme.name)} />
                ),
              )}
            </div>
            <Enforcement agentId={agentId} />
          </>
        )}
      </div>
    </section>
  );
}

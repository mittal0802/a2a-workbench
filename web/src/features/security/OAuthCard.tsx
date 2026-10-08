import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";
import type { SchemeOverview } from "../../lib/types";

const FLOW_TEXT: Record<string, string> = {
  client_credentials: "Sign in with a client ID and secret",
  authorization_code: "Sign in through your browser",
  device_code: "Sign in with a code on another device",
  password: "Sign in with a username and password (deprecated flow)",
  implicit: "Browser sign-in that returns the token directly (deprecated flow)",
};

/** Plain-language summary of an OAuth flow. */
export function flowSummary(flow: string): string {
  return FLOW_TEXT[flow] ?? flow;
}

function expiresIn(iso: string | null): string | null {
  if (!iso) return null;
  const min = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (min <= 0) return "expired — renewed on the next call";
  return min < 60 ? `expires in ${min} min` : `expires in ${Math.round(min / 60)} h`;
}

const inputProps = { className: "jsonedit", style: { minHeight: 0 } } as const;

/** OAuth 2.0 / OpenID Connect sign-in for one security scheme. */
export function OAuthCard({
  agentId,
  scheme,
  requiredScopes,
  needed,
}: {
  agentId: string;
  scheme: SchemeOverview;
  requiredScopes: string[];
  needed: boolean;
}) {
  const qc = useQueryClient();
  const flow = scheme.flows?.[0] ?? "";
  const scopes = scheme.scopes ?? {};
  const [chosen, setChosen] = useState<string[]>(requiredScopes);
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [method, setMethod] = useState<"client_secret_post" | "client_secret_basic">("client_secret_post");
  const [token, setToken] = useState("");
  const done = () => qc.invalidateQueries({ queryKey: ["security", agentId] });
  const signIn = useMutation({
    mutationFn: () =>
      api.oauthSignIn(agentId, scheme.name, {
        flow: flow as "client_credentials" | "password",
        client_id: clientId,
        ...(secret ? { client_secret: secret } : {}),
        ...(flow === "password" ? { username, password } : {}),
        scopes: chosen,
        auth_method: method,
      }),
    onSuccess: done,
  });
  const paste = useMutation({
    mutationFn: () => api.putCredential(agentId, scheme.name, { kind: "oauth2", access_token: token }),
    onSuccess: done,
  });
  const signOut = useMutation({ mutationFn: () => api.deleteCredential(agentId, scheme.name), onSuccess: done });
  const cred = scheme.credential;
  const direct = flow === "client_credentials" || flow === "password";

  return (
    <div className="card">
      <div className="card-h">
        <h3 style={{ fontSize: 14, fontWeight: 600 }}>{scheme.label}</h3>
        <span className="spacer" />
        {cred?.readable ? (
          <span className="status">
            <i />
            Signed in
          </span>
        ) : needed ? (
          <span className="state s-warn">Needed</span>
        ) : (
          <span className="tag">Not signed in</span>
        )}
      </div>
      <div className="card-b">
        <p style={{ marginBottom: 4 }}>{flowSummary(flow)}</p>
        {scheme.description && (
          <details style={{ marginBottom: 8 }}>
            <summary className="no" style={{ cursor: "pointer", fontSize: 12.5 }}>
              Note from the agent
            </summary>
            <p className="no" style={{ fontSize: 12.5, marginTop: 4 }}>
              {scheme.description}
            </p>
          </details>
        )}
        {cred && (
          <div className="row">
            <span>
              {cred.preview}
              {expiresIn(cred.expires_at) && <span className="no"> · {expiresIn(cred.expires_at)}</span>}
            </span>
            <button className="btn ghost" style={{ color: "var(--red)" }} onClick={() => signOut.mutate()}>
              Sign out
            </button>
          </div>
        )}
        {direct ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              signIn.mutate();
            }}
          >
            <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
              Client ID
              <input {...inputProps} aria-label="Client ID" value={clientId} onChange={(e) => setClientId(e.target.value)} />
            </label>
            <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
              Client secret{flow === "password" ? " (if your client has one)" : ""}
              <input {...inputProps} type="password" aria-label="Client secret" value={secret} onChange={(e) => setSecret(e.target.value)} />
            </label>
            {flow === "password" && (
              <>
                <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
                  Username
                  <input {...inputProps} aria-label="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
                </label>
                <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
                  Password
                  <input {...inputProps} type="password" aria-label="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
                </label>
              </>
            )}
            {Object.keys(scopes).length > 0 && (
              <fieldset style={{ border: 0, marginTop: 10 }}>
                <legend className="lbl2" style={{ fontSize: 12.5 }}>
                  Access to request
                </legend>
                {Object.entries(scopes).map(([name, description]) => (
                  <label key={name} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, marginTop: 4 }}>
                    <input
                      type="checkbox"
                      checked={chosen.includes(name)}
                      onChange={(e) => setChosen(e.target.checked ? [...chosen, name] : chosen.filter((s) => s !== name))}
                    />
                    <span>
                      <span className="mono">{name}</span>
                      {requiredScopes.includes(name) && <span className="tag" style={{ marginLeft: 6 }}>required</span>}
                      <div className="no" style={{ fontSize: 12 }}>
                        {description}
                      </div>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
            <details style={{ marginTop: 8 }}>
              <summary className="no" style={{ cursor: "pointer", fontSize: 12.5 }}>
                Advanced
              </summary>
              <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 6 }}>
                Send the client credentials
                <select
                  aria-label="Client authentication"
                  value={method}
                  onChange={(e) => setMethod(e.target.value as typeof method)}
                  style={{ marginLeft: 8 }}
                >
                  <option value="client_secret_post">in the request body</option>
                  <option value="client_secret_basic">as an HTTP Basic header</option>
                </select>
              </label>
            </details>
            <button className="btn primary" style={{ marginTop: 12 }} disabled={!clientId || signIn.isPending}>
              {signIn.isPending ? "Signing in…" : cred ? "Sign in again" : "Sign in"}
            </button>
          </form>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              paste.mutate();
            }}
          >
            <p className="no" style={{ fontSize: 12.5 }}>
              Browser and device sign-in for this flow is coming in the next update. Meanwhile you can paste an access
              token you already have.
            </p>
            <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
              Access token
              <input {...inputProps} type="password" aria-label="Access token" value={token} onChange={(e) => setToken(e.target.value)} />
            </label>
            <button className="btn" style={{ marginTop: 10 }} disabled={!token || paste.isPending}>
              Save token
            </button>
          </form>
        )}
        {(signIn.isError || paste.isError || signOut.isError) && (
          <div className="err">{((signIn.error ?? paste.error ?? signOut.error) as Error).message}</div>
        )}
      </div>
    </div>
  );
}

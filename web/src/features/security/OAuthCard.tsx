import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, api } from "../../lib/api";
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
  const browser = flow === "authorization_code" || flow === "implicit" || scheme.type === "openIdConnect";
  const [device, setDevice] = useState<{ flow_id: string; user_code: string; verification_uri: string; verification_uri_complete: string | null; interval: number } | null>(null);
  const [deviceDone, setDeviceDone] = useState(false);
  const [deviceError, setDeviceError] = useState<string | null>(null);
  const startBrowser = useMutation({
    mutationFn: () =>
      api.oauthStart(agentId, scheme.name, { client_id: clientId, ...(secret ? { client_secret: secret } : {}), scopes: chosen }),
    onSuccess: (r) => {
      window.open(r.authorize_url, "a2aw-oauth", "width=520,height=700");
    },
  });
  const startDevice = useMutation({
    mutationFn: () =>
      api.oauthDevice(agentId, scheme.name, { client_id: clientId, ...(secret ? { client_secret: secret } : {}), scopes: chosen }),
    onSuccess: (d) => {
      setDeviceDone(false);
      setDeviceError(null);
      setDevice(d);
    },
  });
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin === window.location.origin && e.data?.type === "a2aw-oauth") done();
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  });
  useEffect(() => {
    if (!device || deviceDone || deviceError) return;
    const timer = setTimeout(
      async () => {
        try {
          const r = await api.pollDevice(device.flow_id);
          if (r.status === "signed_in") {
            setDeviceDone(true);
            done();
          } else {
            setDevice({ ...device });
          }
        } catch (err) {
          setDeviceError(err instanceof Error ? err.message : String(err));
        }
      },
      Math.max(device.interval, 0) * 1000 + 50,
    );
    return () => clearTimeout(timer);
  }, [device, deviceDone, deviceError]);
  const redirectUri = `${window.location.origin}/oauth/callback`;
  const scopePicker = Object.keys(scopes).length > 0 && (
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
  );
  const clientFields = (secretLabel: string) => (
    <>
      <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
        Client ID
        <input {...inputProps} aria-label="Client ID" value={clientId} onChange={(e) => setClientId(e.target.value)} />
      </label>
      <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
        {secretLabel}
        <input {...inputProps} type="password" aria-label="Client secret" value={secret} onChange={(e) => setSecret(e.target.value)} />
      </label>
    </>
  );

  return (
    <div className="card">
      <div className="card-h">
        <h3 style={{ fontSize: 14, fontWeight: 600 }}>{scheme.label}</h3>
        <span className="spacer" />
        {cred?.renewal_error ? (
          <span className="state s-warn">Sign in again</span>
        ) : cred?.readable ? (
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
        {cred?.renewal_error && (
          <div className="note warn" role="status">
            Your session ended and could not be renewed. Sign in again below.
            <small className="mono">{cred.renewal_error}</small>
          </div>
        )}
        {cred && (
          <div className="row">
            <span>
              {cred.preview}
              {!cred.renewal_error && expiresIn(cred.expires_at) && <span className="no"> · {expiresIn(cred.expires_at)}</span>}
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
            {clientFields(flow === "password" ? "Client secret (if your client has one)" : "Client secret")}
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
            {scopePicker}
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
        ) : browser ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              startBrowser.mutate();
            }}
          >
            {clientFields("Client secret (only for confidential clients)")}
            {scopePicker}
            <p className="no" style={{ fontSize: 12, marginTop: 8 }}>
              Register this redirect URI with the provider: <span className="mono">{redirectUri}</span>
              {flow === "authorization_code" && " · PKCE (S256) is always used"}
            </p>
            <button className="btn primary" style={{ marginTop: 10 }} disabled={!clientId || startBrowser.isPending}>
              Sign in with your browser
            </button>
          </form>
        ) : flow === "device_code" ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              startDevice.mutate();
            }}
          >
            {clientFields("Client secret (if your client has one)")}
            {scopePicker}
            {device && !deviceDone && !deviceError && (
              <div className="note warn" style={{ display: "block" }}>
                Open{" "}
                <a href={device.verification_uri_complete ?? device.verification_uri} target="_blank" rel="noreferrer">
                  {device.verification_uri}
                </a>{" "}
                and enter <b className="mono" style={{ fontSize: 15 }}>{device.user_code}</b>
                <small>Waiting for you to approve…</small>
              </div>
            )}
            {deviceDone && <div className="note ok">Signed in on the other device.</div>}
            {deviceError && <div className="err">{deviceError}</div>}
            <button className="btn primary" style={{ marginTop: 10 }} disabled={!clientId || startDevice.isPending}>
              Get a sign-in code
            </button>
          </form>
        ) : (
          <p className="no">This scheme declares no OAuth flow the Workbench can run.</p>
        )}
        {!direct && (
          <details style={{ marginTop: 10 }}>
            <summary className="no" style={{ cursor: "pointer", fontSize: 12.5 }}>
              I already have an access token
            </summary>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                paste.mutate();
              }}
            >
              <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
                Access token
                <input {...inputProps} type="password" aria-label="Access token" value={token} onChange={(e) => setToken(e.target.value)} />
              </label>
              <button className="btn" style={{ marginTop: 10 }} disabled={!token || paste.isPending}>
                Save token
              </button>
            </form>
          </details>
        )}
        {(signIn.isError || paste.isError || signOut.isError || startBrowser.isError || startDevice.isError) && (
          <div className="err" role="alert">
            {((signIn.error ?? paste.error ?? signOut.error ?? startBrowser.error ?? startDevice.error) as Error).message}
            {signIn.error instanceof ApiError && typeof signIn.error.detail.hint === "string" && (
              <div style={{ marginTop: 6, color: "var(--text)" }}>
                <b>Why: </b>
                {signIn.error.detail.hint}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

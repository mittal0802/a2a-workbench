import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link } from "react-router";
import { api } from "../../lib/api";
import type { SecurityOverview } from "../../lib/types";
import { OAuthCard } from "./OAuthCard";
import { SchemeCard } from "./SecurityView";

function credentialsKey(s?: SecurityOverview): string {
  return JSON.stringify((s?.schemes ?? []).map((x) => [x.name, x.credential?.preview, x.credential?.updated_at]));
}

/** Sign-in window over the chat: the agent's sign-in options, then Retry or Continue once a credential is saved. */
export function SignInDialog({
  agentId,
  agentName,
  open,
  reason,
  action,
  onOpenChange,
  onDone,
}: {
  agentId: string;
  agentName: string;
  open: boolean;
  reason?: string;
  action: "retry" | "continue";
  onOpenChange: (v: boolean) => void;
  onDone: () => void;
}) {
  const sec = useQuery({ queryKey: ["security", agentId], queryFn: () => api.security(agentId), enabled: open });
  const atOpen = useMemo(() => (open ? credentialsKey(sec.data) : ""), [open, sec.dataUpdatedAt === 0]); // eslint-disable-line react-hooks/exhaustive-deps
  const changed = open && !!sec.data && atOpen !== "" && credentialsKey(sec.data) !== atOpen;
  const s = sec.data;
  const shown = s ? (s.missing.length ? s.schemes.filter((x) => s.missing.includes(x.name)) : s.schemes) : [];
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim on">
          <Dialog.Content className="modal" style={{ width: "min(720px, 94vw)", maxHeight: "88vh", overflow: "auto" }} aria-describedby={undefined}>
            <div className="mh">
              <Dialog.Title asChild>
                <h3>Sign in to {agentName}</h3>
              </Dialog.Title>
              <p>The agent refused the request until you sign in.</p>
            </div>
            <div className="mb">
              {reason && (
                <div className="note warn" style={{ marginBottom: 12, display: "block" }}>
                  <small className="mono" style={{ wordBreak: "break-word" }}>{reason}</small>
                </div>
              )}
              {!s && <div className="no">Loading…</div>}
              {s?.status === "not_required" && (
                <p className="no">
                  The agent card declares no sign-in, yet the agent answered 401. That is an issue with the agent: its card should
                  list the security schemes it enforces (A2A §4.5, §7.3).
                </p>
              )}
              {changed && (
                <div className="note ok" style={{ marginBottom: 12 }}>
                  <span className="i">✓</span>
                  <div>Credentials saved.</div>
                  <span className="spacer" />
                  <button
                    className="btn primary"
                    onClick={() => {
                      onOpenChange(false);
                      onDone();
                    }}
                  >
                    {action === "retry" ? "Retry the message" : "Continue the task"}
                  </button>
                </div>
              )}
              <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
                {shown.map((scheme) =>
                  scheme.type === "oauth2" || scheme.type === "openIdConnect" ? (
                    <OAuthCard key={scheme.name} agentId={agentId} scheme={scheme} requiredScopes={s?.required_scopes?.[scheme.name] ?? []} needed={!!s?.missing.includes(scheme.name)} />
                  ) : (
                    <SchemeCard key={scheme.name} agentId={agentId} scheme={scheme} needed={!!s?.missing.includes(scheme.name)} />
                  ),
                )}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
                <Link to={`/agents/${agentId}/security`} className="try" onClick={() => onOpenChange(false)}>
                  Open the Security tab
                </Link>
                <span className="spacer" />
                <Dialog.Close asChild>
                  <button className="btn">Close</button>
                </Dialog.Close>
              </div>
            </div>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

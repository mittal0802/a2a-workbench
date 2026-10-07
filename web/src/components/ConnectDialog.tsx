import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "../lib/api";
import { bindingLabel } from "../lib/labels";
import type { Agent, CardPreview, SignatureStatus } from "../lib/types";
import { Avatar } from "./Avatar";

const SIGNATURE_COPY: Record<SignatureStatus, string> = {
  verified: "signed card ✓",
  invalid: "signature invalid",
  unsigned: "not signed",
  unverifiable: "signature can't be checked",
};

/** Plain-language explanation of a failed card fetch. */
export function connectErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.category === "transport") return "We couldn't reach that address. Is the agent running?";
    if (err.category === "protocol") return "That address answered, but not with a valid A2A agent card.";
    if (err.status === 409) return "This agent is already connected.";
    return err.message;
  }
  return String(err);
}

/** Two-step dialog: find an agent by address, then connect with a chosen interface. */
export function ConnectDialog({
  open,
  onOpenChange,
  onConnected,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConnected: (agent: Agent) => void;
}) {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<CardPreview | null>(null);
  const [choice, setChoice] = useState<string | null>(null);

  const find = useMutation({
    mutationFn: () => api.previewCard(url.trim()),
    onSuccess: (p) => {
      setPreview(p);
      setChoice(p.default_interface_url);
    },
  });
  const connect = useMutation({
    mutationFn: async () => {
      let agent = await api.addAgent(url.trim());
      if (choice && choice !== agent.selected_interface_url) agent = await api.patchAgent(agent.id, choice);
      return agent;
    },
    onSuccess: (agent) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      reset();
      onConnected(agent);
    },
  });

  function reset() {
    setUrl("");
    setPreview(null);
    setChoice(null);
    find.reset();
    connect.reset();
  }

  const card = preview?.card;
  const caps = card?.capabilities ?? {};
  const facts = [
    `${(card?.skills ?? []).length} skills`,
    caps.streaming ? "streaming" : null,
    caps.pushNotifications ? "notifications" : null,
    preview ? SIGNATURE_COPY[preview.signature_status] : null,
  ].filter(Boolean);

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="scrim on">
          <Dialog.Content className="modal" aria-describedby={undefined}>
            <div className="mh">
              <Dialog.Title asChild>
                <h3>Connect an agent</h3>
              </Dialog.Title>
              <p>Paste the agent's address. We'll read its agent card and set everything up.</p>
            </div>
            <div className="stepper">
              <div className="on" />
              <div className={preview ? "on" : ""} />
            </div>
            <form
              className="mb"
              onSubmit={(e) => {
                e.preventDefault();
                if (preview) connect.mutate();
                else if (url.trim()) find.mutate();
              }}
            >
              <label className="lbl2" htmlFor="agent-url">
                Agent address
              </label>
              <div className="inp">
                <input
                  id="agent-url"
                  autoFocus
                  value={url}
                  placeholder="http://localhost:9999"
                  onChange={(e) => {
                    setUrl(e.target.value);
                    setPreview(null);
                  }}
                />
                {!preview && (
                  <button type="submit" className="btn" disabled={!url.trim() || find.isPending}>
                    {find.isPending ? "Looking…" : "Find agent"}
                  </button>
                )}
              </div>
              {find.isError && (
                <div className="err" role="alert">
                  {connectErrorText(find.error)}
                  <div className="no mono" style={{ marginTop: 4 }}>
                    {find.error instanceof Error ? find.error.message : ""}
                  </div>
                </div>
              )}
              {preview && card && (
                <>
                  <div className="found">
                    <Avatar name={card.name ?? "?"} />
                    <div style={{ flex: 1 }}>
                      <b>{card.name}</b>
                      {card.provider?.organization ? ` by ${card.provider.organization}` : ""}
                      <small>{facts.join(" · ")}</small>
                    </div>
                  </div>
                  <div className="lbl2" style={{ marginTop: 18 }}>
                    How should we connect?
                  </div>
                  {preview.interfaces.map((i) => (
                    <label key={i.url} className={`choice ${choice === i.url ? "on" : ""}`}>
                      <input
                        type="radio"
                        name="iface"
                        className="sr-only"
                        checked={choice === i.url}
                        disabled={!i.supported}
                        onChange={() => setChoice(i.url)}
                        aria-label={`${bindingLabel(i.binding)} A2A ${i.protocol_version} ${i.url}`}
                      />
                      <span className="rd" />
                      <div>
                        {bindingLabel(i.binding)}
                        {i.url === preview.default_interface_url && (
                          <span className="tag" style={{ marginLeft: 6 }}>
                            Recommended
                          </span>
                        )}
                        {!i.supported && (
                          <span className="tag" style={{ marginLeft: 6 }}>
                            coming soon
                          </span>
                        )}
                        <small>
                          A2A {i.protocol_version || "?"} · {i.url}
                        </small>
                      </div>
                    </label>
                  ))}
                  {connect.isError && (
                    <div className="err" role="alert">
                      {connectErrorText(connect.error)}
                    </div>
                  )}
                </>
              )}
              <div className="mf" style={{ padding: "16px 0 6px" }}>
                <Dialog.Close asChild>
                  <button type="button" className="btn ghost">
                    Cancel
                  </button>
                </Dialog.Close>
                {preview && (
                  <button type="submit" className="btn primary" disabled={!choice || connect.isPending}>
                    {connect.isPending ? "Connecting…" : "Connect"}
                  </button>
                )}
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

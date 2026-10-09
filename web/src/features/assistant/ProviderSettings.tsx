import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";
import type { ProviderInfo } from "../../lib/types";

const NAMES: Record<string, string> = { anthropic: "Anthropic", openai: "OpenAI or compatible", gemini: "Google Gemini" };

/** Dialog for one provider's API key and base URL; a stored key is only ever shown masked. */
export function ProviderSettings({
  open,
  onOpenChange,
  provider,
  info,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  provider: string;
  info?: ProviderInfo;
}) {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const compatible = provider === "openai";
  const url = compatible ? (baseUrl ?? info?.base_url ?? "") : "";
  const done = () => {
    setKey("");
    qc.invalidateQueries({ queryKey: ["assistant-providers"] });
  };
  const save = useMutation({
    mutationFn: () => api.putAssistantProvider(provider, { api_key: key, base_url: compatible && url ? url : null }),
    onSuccess: done,
  });
  const remove = useMutation({ mutationFn: () => api.deleteAssistantProvider(provider), onSuccess: done });
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim on">
          <Dialog.Content className="modal" aria-describedby={undefined}>
            <div className="mh">
              <Dialog.Title asChild>
                <h3>{NAMES[provider] ?? provider}</h3>
              </Dialog.Title>
              <p>Your own API key, stored encrypted on this machine and never shown again.</p>
            </div>
            <form
              className="mb"
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate();
              }}
            >
              <div className="no" style={{ fontSize: 12.5, marginBottom: 8 }}>
                {info?.configured
                  ? `Current key: ${info.preview} (${info.source === "env" ? "from the environment" : "saved"})`
                  : "No key yet."}
              </div>
              <label className="lbl2" style={{ display: "block", fontSize: 12.5 }}>
                API key
                <input className="jsonedit" style={{ minHeight: 0 }} type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
              </label>
              {provider === "openai" && (
                <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
                  Base URL (for Ollama, vLLM, LM Studio…; empty for OpenAI)
                  <input className="jsonedit" style={{ minHeight: 0 }} value={url} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://localhost:11434/v1" />
                </label>
              )}
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <button className="btn primary" disabled={!key || save.isPending}>
                  Save key
                </button>
                {info?.source === "stored" && (
                  <button type="button" className="btn ghost" style={{ color: "var(--red)" }} onClick={() => remove.mutate()}>
                    Remove saved key
                  </button>
                )}
                <div className="spacer" />
                <Dialog.Close asChild>
                  <button type="button" className="btn">
                    Close
                  </button>
                </Dialog.Close>
              </div>
              {(save.isError || remove.isError) && <div className="err">{((save.error ?? remove.error) as Error).message}</div>}
            </form>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

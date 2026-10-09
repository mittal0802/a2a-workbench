import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ConfirmButton } from "../../components/ConfirmButton";
import { api } from "../../lib/api";
import type { ProviderInfo } from "../../lib/types";

const INFO: Record<string, { name: string; env: string; console: string; blurb: string }> = {
  anthropic: {
    name: "Anthropic",
    env: "ANTHROPIC_API_KEY",
    console: "https://console.anthropic.com/settings/keys",
    blurb: "Claude models. Default model: claude-sonnet-5-5.",
  },
  openai: {
    name: "OpenAI or compatible",
    env: "OPENAI_API_KEY",
    console: "https://platform.openai.com/api-keys",
    blurb: "OpenAI, or any server that speaks the OpenAI API (Ollama, vLLM, LM Studio…).",
  },
  gemini: {
    name: "Google Gemini",
    env: "GEMINI_API_KEY or GOOGLE_API_KEY",
    console: "https://aistudio.google.com/apikey",
    blurb: "Gemini models through the Google AI API.",
  },
};

const PRESETS = [
  { label: "OpenAI", url: "" },
  { label: "Ollama", url: "http://localhost:11434/v1" },
  { label: "LM Studio", url: "http://localhost:1234/v1" },
  { label: "vLLM", url: "http://localhost:8000/v1" },
];

function ProviderCard({ info }: { info: ProviderInfo }) {
  const qc = useQueryClient();
  const meta = INFO[info.provider];
  const compatible = info.provider === "openai";
  const [key, setKey] = useState("");
  const [show, setShow] = useState(false);
  const [baseUrl, setBaseUrl] = useState(info.base_url ?? "");
  const refresh = () => qc.invalidateQueries({ queryKey: ["assistant-providers"] });
  const save = useMutation({
    mutationFn: () => api.putAssistantProvider(info.provider, { api_key: key, base_url: compatible && baseUrl ? baseUrl : null }),
    onSuccess: () => {
      setKey("");
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: () => api.deleteAssistantProvider(info.provider), onSuccess: refresh });
  const status = info.configured
    ? info.source === "env"
      ? `From the environment (${meta.env}) · ${info.preview}`
      : `Saved ${info.preview}${info.base_url ? ` · ${info.base_url}` : ""}`
    : "Not set";
  return (
    <section className="card" aria-label={meta.name} style={{ marginBottom: 14 }}>
      <div className="card-h">
        <h3 style={{ fontSize: 14, fontWeight: 600 }}>{meta.name}</h3>
        <span className="spacer" />
        <span className={info.configured ? "status" : "tag"}>
          {info.configured && <i />}
          {status}
        </span>
      </div>
      <form
        className="card-b"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <p className="no" style={{ fontSize: 12.5, marginBottom: 8 }}>
          {meta.blurb}{" "}
          <a href={meta.console} target="_blank" rel="noreferrer noopener">
            Get a key
          </a>
        </p>
        {compatible && (
          <>
            <div className="seg" role="group" aria-label="Server" style={{ marginBottom: 6 }}>
              {PRESETS.map((p) => (
                <button type="button" key={p.label} className={baseUrl === p.url ? "on" : ""} onClick={() => setBaseUrl(p.url)}>
                  {p.label}
                </button>
              ))}
            </div>
            <label className="lbl2" style={{ display: "block", fontSize: 12.5 }}>
              Base URL (empty for OpenAI)
              <input className="jsonedit" style={{ minHeight: 0 }} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
            </label>
          </>
        )}
        <label className="lbl2" style={{ display: "block", fontSize: 12.5, marginTop: 8 }}>
          {info.configured ? "Replace API key" : "API key"}
          <span style={{ display: "flex", gap: 6 }}>
            <input
              className="jsonedit"
              style={{ minHeight: 0, flex: 1 }}
              type={show ? "text" : "password"}
              autoComplete="off"
              aria-label="API key"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={info.configured ? "Paste a new key to replace it" : "Paste your key"}
            />
            <button type="button" className="btn" onClick={() => setShow(!show)} aria-label={show ? "Hide key" : "Show key"}>
              {show ? "Hide" : "Show"}
            </button>
          </span>
        </label>
        <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
          <button className="btn primary" disabled={!key || save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
          {info.source === "stored" && (
            <ConfirmButton label="Remove saved key" question={`Remove the saved ${meta.name} key?`} confirmLabel="Remove" className="btn ghost" onConfirm={() => remove.mutate()}>
              Remove saved key
            </ConfirmButton>
          )}
          {save.isSuccess && <span className="no">Saved.</span>}
        </div>
        {(save.isError || remove.isError) && <div className="err">{((save.error ?? remove.error) as Error).message}</div>}
      </form>
    </section>
  );
}

/** Workbench settings: the Assistant's model providers and their API keys. */
export function SettingsPage() {
  const providers = useQuery({ queryKey: ["assistant-providers"], queryFn: api.assistantProviders });
  return (
    <div style={{ overflow: "auto", flex: 1 }}>
      <div className="head" style={{ paddingBottom: 14, borderBottom: "1px solid var(--line)" }}>
        <h1>Settings</h1>
      </div>
      <div style={{ padding: "18px 24px", maxWidth: 760 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Model providers</h2>
        <p className="no" style={{ fontSize: 12.5, marginBottom: 14 }}>
          Keys for the Assistant. They are encrypted on this machine, never shown again and never sent anywhere but the provider.
          A key in the environment is used when none is saved here.
        </p>
        {providers.isError && <div className="err">{(providers.error as Error).message}</div>}
        {providers.data?.map((p) => (
          <ProviderCard key={`${p.provider}-${p.source}-${p.preview ?? ""}`} info={p} />
        ))}
      </div>
    </div>
  );
}

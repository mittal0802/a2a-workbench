import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import { formatBytes } from "../../lib/parts";
import { DEFAULT_OPTIONS, type Agent, type PartInput, type SendOptions } from "../../lib/types";
import { profileLabel } from "./NetworkConditions";
import { OptionsMenu } from "./OptionsMenu";

type Attachment = { blob_id: string; filename: string; media_type: string; size: number };

/** Message editor with file, URL and JSON parts, send options, reply and stop controls. */
export function Composer({
  agent,
  onSend,
  onStop,
  replying,
  busy,
  prefill,
}: {
  agent: Agent;
  onSend: (parts: PartInput[], options: SendOptions) => void;
  onStop: () => void;
  replying: boolean;
  busy: boolean;
  prefill?: string;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<Attachment[]>([]);
  const [urls, setUrls] = useState<string[]>([]);
  const [urlDraft, setUrlDraft] = useState<string | null>(null);
  const [dataText, setDataText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [options, setOptions] = useState<SendOptions>(DEFAULT_OPTIONS);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (prefill) setText(prefill);
  }, [prefill]);

  async function attach(list: FileList | null) {
    if (!list) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(list)) {
        const blob = await api.uploadBlob(file);
        setFiles((f) => [...f, { blob_id: blob.id, filename: blob.filename ?? file.name, media_type: blob.media_type, size: blob.size }]);
      }
    } catch (e) {
      setError(`Upload failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setUploading(false);
    }
  }

  function submit() {
    const parts: PartInput[] = [];
    if (text.trim()) parts.push({ kind: "text", text });
    for (const f of files) parts.push({ kind: "file", blob_id: f.blob_id });
    const allUrls = [...urls, ...(urlDraft?.trim() ? [urlDraft.trim()] : [])];
    for (const u of allUrls) parts.push({ kind: "file", url: u });
    if (dataText !== null && dataText.trim()) {
      try {
        parts.push({ kind: "data", data: JSON.parse(dataText) });
      } catch (e) {
        setError(`The JSON data is not valid JSON: ${e instanceof Error ? e.message : e}`);
        return;
      }
    }
    if (parts.length === 0) return;
    setError(null);
    onSend(parts, options);
    setText("");
    setFiles([]);
    setUrls([]);
    setUrlDraft(null);
    setDataText(null);
  }

  return (
    <div className="composer">
      {options.faults && (
        <div className="note warn" style={{ maxWidth: 760, margin: "0 auto 8px", alignItems: "center" }}>
          <span className="i">!</span>
          <div>
            Network conditions: {profileLabel(options.faults)}
            <small>Injected beneath the SDK. “Once” rules fire once per conversation; switching profiles starts over.</small>
          </div>
          <button className="btn ghost" style={{ marginLeft: "auto" }} onClick={() => setOptions({ ...options, faults: null })}>
            Turn off
          </button>
        </div>
      )}
      <div className="cbox">
        {(files.length > 0 || urls.length > 0) && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", padding: "10px 12px 0" }}>
            {files.map((f) => (
              <span key={f.blob_id} className="chipx">
                📎 {f.filename} · {formatBytes(f.size)}
                <button aria-label={`Remove ${f.filename}`} onClick={() => setFiles(files.filter((x) => x !== f))}>
                  ×
                </button>
              </span>
            ))}
            {urls.map((u) => (
              <span key={u} className="chipx">
                🔗 {u}
                <button aria-label={`Remove ${u}`} onClick={() => setUrls(urls.filter((x) => x !== u))}>
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        <textarea
          placeholder={`Message ${agent.card.name ?? "the agent"}…`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
        />
        {urlDraft !== null && (
          <div style={{ padding: "0 12px 8px" }}>
            <input
              aria-label="File URL"
              className="jsonedit"
              style={{ minHeight: 0 }}
              placeholder="https://example.com/file.pdf"
              value={urlDraft}
              onChange={(e) => setUrlDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && urlDraft.trim()) {
                  e.preventDefault();
                  setUrls([...urls, urlDraft.trim()]);
                  setUrlDraft("");
                }
              }}
            />
          </div>
        )}
        {dataText !== null && (
          <div style={{ padding: "0 12px 8px" }}>
            <textarea
              aria-label="JSON data"
              className="jsonedit"
              placeholder='{"key": "value"}'
              value={dataText}
              onChange={(e) => setDataText(e.target.value)}
            />
          </div>
        )}
        {error && (
          <div className="err" style={{ margin: "0 12px 8px" }} role="alert">
            {error}
          </div>
        )}
        <div className="cbar">
          <input ref={fileInput} type="file" multiple hidden onChange={(e) => attach(e.target.files)} aria-label="Choose files" />
          <button className="ib" title="Attach file" aria-label="Attach file" onClick={() => fileInput.current?.click()} disabled={uploading}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M21 12l-9 9a5 5 0 01-7-7l9-9a3.5 3.5 0 015 5l-9 9a2 2 0 01-3-3l8-8" />
            </svg>
          </button>
          <button className="ib" title="Add file by URL" aria-label="Add file by URL" onClick={() => setUrlDraft(urlDraft === null ? "" : null)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M10 13a5 5 0 007 0l3-3a5 5 0 00-7-7l-1 1M14 11a5 5 0 00-7 0l-3 3a5 5 0 007 7l1-1" />
            </svg>
          </button>
          <button className="ib" title="Add JSON data" aria-label="Add JSON data" onClick={() => setDataText(dataText === null ? "" : null)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M8 3H6a2 2 0 00-2 2v4a2 2 0 01-2 2 2 2 0 012 2v4a2 2 0 002 2h2M16 3h2a2 2 0 012 2v4a2 2 0 002 2 2 2 0 00-2 2v4a2 2 0 01-2 2h-2" />
            </svg>
          </button>
          <OptionsMenu agent={agent} value={options} onChange={setOptions} />
          {replying && <span className="reply">Replying to the open question</span>}
          <div className="spacer" />
          {busy && (
            <button className="ib" style={{ color: "var(--red)" }} onClick={onStop}>
              Stop task
            </button>
          )}
          <button className="send" aria-label="Send" onClick={submit} disabled={uploading}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>
      <div className="hint">Every message is sent with the official A2A SDK. Open Inspect to see exactly what went over the wire.</div>
    </div>
  );
}

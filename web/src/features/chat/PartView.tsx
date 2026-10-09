import { useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { JsonView } from "../../components/JsonView";
import { base64Size, dataUrl, formatBytes, partKind } from "../../lib/parts";
import type { A2APart } from "../../lib/types";

const SAFE_URL = /^https?:\/\//i;
const MARKDOWN_TYPES = new Set(["", "text/plain", "text/markdown"]);

const FRAME_CSP =
  "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; font-src https: data:\">";

/** An agent's HTML document, isolated: sandboxed frame (no scripts, no same-origin), with its source viewable. */
export function HtmlFrame({ html }: { html: string }) {
  const [source, setSource] = useState(false);
  return (
    <div className="htmlpart">
      <div className="htmlpart-h">
        <span className="no">HTML · scripts disabled</span>
        <span className="spacer" />
        <button type="button" className="ib" onClick={() => setSource(!source)}>
          {source ? "View rendered" : "View source"}
        </button>
      </div>
      {source ? (
        <pre className="code">{html}</pre>
      ) : (
        <iframe title="HTML from the agent" sandbox="" srcDoc={FRAME_CSP + html} className="htmlframe" />
      )}
    </div>
  );
}

/** Markdown for agent text: GitHub-flavoured, embedded HTML sanitized (no scripts or handlers), links open in a new tab. */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, rehypeSanitize]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

/** Renders one A2A message or artifact part according to its content and media type.
 *
 * With ``markdown``, text without a media type (or ``text/plain``) is rendered as
 * Markdown, as agents commonly send it; ``text/markdown`` always is.
 */
export function PartView({ part, markdown = false }: { part: A2APart; markdown?: boolean }) {
  const kind = partKind(part);
  const media = part.mediaType ?? "";
  const name = part.filename ?? (media || "file");
  let body;
  if (kind === "text") {
    body =
      media === "text/html" ? (
        <HtmlFrame html={part.text ?? ""} />
      ) : media === "text/markdown" || (markdown && MARKDOWN_TYPES.has(media)) ? (
        <Markdown text={part.text ?? ""} />
      ) : (
        <div className="whitespace-pre-wrap">{part.text}</div>
      );
  } else if (kind === "raw") {
    const src = dataUrl(part);
    if (media.startsWith("image/")) body = <img className="part-img" src={src} alt={name} />;
    else if (media.startsWith("audio/")) body = <audio controls src={src} aria-label={name} />;
    else if (media.startsWith("video/")) body = <video controls src={src} aria-label={name} className="part-img" />;
    else
      body = (
        <a className="att" href={src} download={part.filename ?? "file"}>
          <span className="ic">{(media.split("/")[1] ?? "FILE").slice(0, 4).toUpperCase()}</span>
          <span>
            {name}
            <small>
              {formatBytes(base64Size(part.raw ?? ""))} · {media || "unknown type"}
            </small>
          </span>
        </a>
      );
  } else if (kind === "url") {
    const url = part.url ?? "";
    body = SAFE_URL.test(url) ? (
      <div>
        {media.startsWith("image/") && <img className="part-img" src={url} alt={name} />}
        <a className="att" href={url} target="_blank" rel="noreferrer">
          <span className="ic">URL</span>
          <span>
            {part.filename ?? url}
            <small>{media || "linked file"}</small>
          </span>
        </a>
      </div>
    ) : (
      <div className="mono">{url}</div>
    );
  } else if (kind === "data") {
    body = <JsonView value={part.data} />;
  } else {
    body = <div className="no">(empty part)</div>;
  }
  return (
    <div className="part" style={{ marginTop: 4 }}>
      {body}
      {part.metadata && Object.keys(part.metadata).length > 0 && (
        <details style={{ marginTop: 4 }}>
          <summary className="no" style={{ fontSize: 12, cursor: "pointer" }}>
            metadata
          </summary>
          <JsonView value={part.metadata} />
        </details>
      )}
    </div>
  );
}

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { JsonView } from "../../components/JsonView";
import { base64Size, dataUrl, formatBytes, partKind } from "../../lib/parts";
import type { A2APart } from "../../lib/types";

const SAFE_URL = /^https?:\/\//i;

/** Renders one A2A message or artifact part according to its content and media type. */
export function PartView({ part }: { part: A2APart }) {
  const kind = partKind(part);
  const media = part.mediaType ?? "";
  const name = part.filename ?? (media || "file");
  let body;
  if (kind === "text") {
    body =
      media === "text/markdown" ? (
        <div className="markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text ?? ""}</ReactMarkdown>
        </div>
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

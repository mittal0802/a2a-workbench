import type { A2AArtifact, A2APart } from "../../lib/types";
import { PartView } from "./PartView";

/** Merges runs of plain text parts (streamed chunks) into one part each; other parts stay as they are. */
export function joinTextRuns(parts: A2APart[]): A2APart[] {
  const out: A2APart[] = [];
  for (const p of parts) {
    const plain = typeof p.text === "string" && !p.mediaType;
    const prev = out[out.length - 1];
    if (plain && prev && typeof prev.text === "string" && !prev.mediaType) {
      out[out.length - 1] = { ...prev, text: prev.text + p.text };
    } else {
      out.push(plain ? { ...p } : p);
    }
  }
  return out;
}

/** One (possibly still streaming) artifact with all its parts. */
export function ArtifactCard({
  artifact,
  complete,
  onInspect,
}: {
  artifact: A2AArtifact;
  complete: boolean;
  onInspect?: () => void;
}) {
  return (
    <div className="result">
      <div className="result-h">
        📦 {artifact.name || "Result"}
        <small>
          · {artifact.parts.length} part{artifact.parts.length === 1 ? "" : "s"}
          {complete ? "" : " · receiving…"}
          {artifact.description ? ` · ${artifact.description}` : ""}
        </small>
        <div className="spacer" />
        {onInspect && (
          <button className="ib" onClick={onInspect}>
            View raw
          </button>
        )}
      </div>
      <div style={{ padding: "8px 14px 12px" }}>
        {joinTextRuns(artifact.parts).map((p, i) => (
          <PartView key={i} part={p} markdown />
        ))}
      </div>
    </div>
  );
}

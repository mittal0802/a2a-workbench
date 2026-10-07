import type { A2AArtifact } from "../../lib/types";
import { PartView } from "./PartView";

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
        {artifact.parts.map((p, i) => (
          <PartView key={i} part={p} />
        ))}
      </div>
    </div>
  );
}

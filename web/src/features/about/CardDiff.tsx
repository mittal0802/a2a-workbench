import { JsonView } from "../../components/JsonView";

export type DiffEntry = { path: string; change: "added" | "removed" | "changed"; public: unknown; extended: unknown };

const VERB = { added: "Adds", removed: "Removes", changed: "Changes" } as const;

/** One-line plain-language description of a card difference. */
export function describeChange(d: DiffEntry): string {
  const skill = /^skills\[([^\]]+)\]$/.exec(d.path);
  if (skill) {
    const value = (d.change === "removed" ? d.public : d.extended) as { name?: string } | null;
    return `${VERB[d.change]} skill “${value?.name ?? skill[1]}”`;
  }
  return `${VERB[d.change]} ${d.path}`;
}

/** What the extended card adds, removes or changes compared with the public card. */
export function CardDiff({ diff }: { diff: DiffEntry[] }) {
  if (diff.length === 0) return <p className="no">The extended card is identical to the public card.</p>;
  return (
    <div>
      {diff.map((d) => (
        <details key={d.path} className="row" style={{ display: "block" }}>
          <summary style={{ cursor: "pointer" }}>
            <span className={`tag ${d.change === "added" ? "g" : ""}`} style={{ marginRight: 8 }}>
              {d.change}
            </span>
            {describeChange(d)}
          </summary>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
            <div>
              <div className="no">Public</div>
              <JsonView value={d.public ?? null} />
            </div>
            <div>
              <div className="no">Extended</div>
              <JsonView value={d.extended ?? null} />
            </div>
          </div>
        </details>
      ))}
    </div>
  );
}

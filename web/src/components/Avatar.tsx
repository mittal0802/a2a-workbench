const PALETTE = ["#5b5bd6", "#1f9d63", "#b7791f", "#2b7fd4", "#c2410c", "#7a5af5", "#0f766e", "#be185d"];

function colorFor(name: string): string {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

/** Square avatar showing the first letter of `name` on a colour derived from it. */
export function Avatar({ name, size = 30 }: { name: string; size?: number }) {
  return (
    <div
      className="emoji"
      aria-hidden
      style={{
        width: size,
        height: size,
        background: `${colorFor(name)}22`,
        color: colorFor(name),
        fontWeight: 700,
        fontSize: size * 0.45,
      }}
    >
      {(name.trim()[0] ?? "?").toUpperCase()}
    </div>
  );
}

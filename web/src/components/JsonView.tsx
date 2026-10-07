import { Fragment, type ReactNode } from "react";

function highlight(json: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(json))) {
    if (m.index > last) out.push(json.slice(last, m.index));
    if (m[1] && m[2]) out.push(<span key={i++} className="k">{m[1]}</span>, m[2]);
    else if (m[1]) out.push(<span key={i++} className="s">{m[1]}</span>);
    else if (m[3]) out.push(<span key={i++} className="b">{m[3]}</span>);
    else out.push(<span key={i++} className="n">{m[4]}</span>);
    last = re.lastIndex;
  }
  out.push(json.slice(last));
  return out;
}

/** Pretty-printed, syntax-highlighted JSON; strings that are not JSON are shown as-is. */
export function JsonView({ value, raw }: { value?: unknown; raw?: string | null }) {
  let text: string;
  if (raw !== undefined) {
    try {
      text = JSON.stringify(JSON.parse(raw ?? ""), null, 2);
    } catch {
      text = raw ?? "";
    }
  } else {
    text = JSON.stringify(value, null, 2) ?? "undefined";
  }
  return (
    <pre className="code">
      {highlight(text).map((n, idx) => (
        <Fragment key={idx}>{n}</Fragment>
      ))}
    </pre>
  );
}

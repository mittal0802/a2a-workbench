import { Fragment } from "react";
import { INTERRUPTED, TERMINAL, stateLabel } from "../../lib/labels";

/** The states a task went through, in order, with the current one highlighted. */
export function TaskProgress({ states, current }: { states: string[]; current: string | null }) {
  return (
    <div className="progress">
      {states.map((s, i) => {
        const isCurrent = s === current && i === states.length - 1;
        const { label, protocol } = stateLabel(s);
        const mark = isCurrent && INTERRUPTED.has(s) ? "!" : isCurrent && !TERMINAL.has(s) ? "…" : "✓";
        const bad = s === "failed" || s === "rejected";
        return (
          <Fragment key={`${s}-${i}`}>
            {i > 0 && <span className="ar">→</span>}
            <span
              className={`p ${isCurrent && !TERMINAL.has(s) ? "now" : ""}`}
              data-current={isCurrent ? "true" : "false"}
              title={protocol}
              style={bad ? { color: "var(--red)" } : undefined}
            >
              <i style={bad ? { background: "var(--red-soft)", color: "var(--red)" } : undefined}>{bad ? "✕" : mark}</i>
              {label}
            </span>
          </Fragment>
        );
      })}
    </div>
  );
}

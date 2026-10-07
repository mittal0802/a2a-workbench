import type { A2AMessage } from "../../lib/types";
import { PartView } from "./PartView";

/** The agent's question when a task waits for input or sign-in. */
export function AskCard({ message, state }: { message: A2AMessage | null; state: string }) {
  const auth = state === "auth_required";
  return (
    <div className="ask" style={auth ? { background: "var(--brand-soft)" } : undefined}>
      <div className="lbl" style={auth ? { color: "var(--brand)" } : undefined} title={state}>
        ● {auth ? "Sign-in needed" : "Waiting for you"}
      </div>
      {message?.parts.length ? (
        message.parts.map((p, i) => <PartView key={i} part={p} />)
      ) : (
        <div className="no">{auth ? "The agent needs you to sign in." : "The agent needs more input."}</div>
      )}
    </div>
  );
}

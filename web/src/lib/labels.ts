export type Tone = "ok" | "warn" | "bad" | "run" | "off" | "auth";

const STATES: Record<string, { label: string; tone: Tone }> = {
  submitted: { label: "Received", tone: "run" },
  working: { label: "Working", tone: "run" },
  input_required: { label: "Needs your input", tone: "warn" },
  auth_required: { label: "Needs sign-in", tone: "auth" },
  completed: { label: "Done", tone: "ok" },
  failed: { label: "Failed", tone: "bad" },
  canceled: { label: "Stopped", tone: "off" },
  rejected: { label: "Declined", tone: "bad" },
  unspecified: { label: "Unknown", tone: "off" },
};

/** Plain-language label and tone for an A2A task state, keeping the protocol name. */
export function stateLabel(state: string): { label: string; tone: Tone; protocol: string } {
  const known = STATES[state];
  return { label: known?.label ?? state, tone: known?.tone ?? "off", protocol: state };
}

const BINDINGS: Record<string, string> = { JSONRPC: "JSON-RPC", "HTTP+JSON": "REST", GRPC: "gRPC" };

/** Display name of a protocol binding. */
export function bindingLabel(binding: string): string {
  return BINDINGS[binding] ?? binding;
}

export const TERMINAL = new Set(["completed", "failed", "canceled", "rejected"]);
export const INTERRUPTED = new Set(["input_required", "auth_required"]);
export const RUNNING = new Set(["submitted", "working"]);

/** CSS class of the state pill for a tone. */
export function toneClass(tone: Tone): string {
  return { ok: "s-ok", warn: "s-warn", bad: "s-bad", run: "s-run", off: "s-off", auth: "s-auth" }[tone];
}

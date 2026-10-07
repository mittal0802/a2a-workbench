import { stateLabel, toneClass } from "../lib/labels";

/** Pill showing an A2A task state in plain language; the protocol name is the tooltip. */
export function StatePill({ state }: { state: string }) {
  const { label, tone, protocol } = stateLabel(state);
  return (
    <span className={`state ${toneClass(tone)}`} title={protocol}>
      <i />
      {label}
    </span>
  );
}

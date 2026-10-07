import * as RadixSwitch from "@radix-ui/react-switch";

/** Accessible on/off switch styled like the design's toggles. */
export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <RadixSwitch.Root
      className={`sw ${checked ? "" : "off"}`}
      checked={checked}
      onCheckedChange={onCheckedChange}
      aria-label={label}
      disabled={disabled}
      style={{ marginLeft: "auto", border: 0 }}
    />
  );
}

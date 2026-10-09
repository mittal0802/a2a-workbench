import { useEffect, useState } from "react";

/** Copies `text()` to the clipboard and briefly shows "Copied". */
export function CopyButton({ text, label = "Copy", className = "ib" }: { text: () => string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);
  return (
    <button
      type="button"
      className={className}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text());
          setCopied(true);
        } catch {
          /* clipboard unavailable (insecure context or denied) */
        }
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}

/** Saves `text` as a file named `filename` through a temporary download link. */
export function downloadText(filename: string, text: string, type = "application/json"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

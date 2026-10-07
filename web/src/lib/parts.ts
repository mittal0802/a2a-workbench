import type { A2APart } from "./types";

export type PartKind = "text" | "raw" | "url" | "data" | "empty";

/** Which content field a part carries. */
export function partKind(p: A2APart): PartKind {
  if (p.text !== undefined) return "text";
  if (p.raw !== undefined) return "raw";
  if (p.url !== undefined) return "url";
  if (p.data !== undefined) return "data";
  return "empty";
}

/** Concatenate the text of all text parts. */
export function joinText(parts: A2APart[]): string {
  return parts
    .filter((p) => p.text !== undefined)
    .map((p) => p.text)
    .join("");
}

/** A data: URL for a raw (base64) part. */
export function dataUrl(p: A2APart): string {
  return `data:${p.mediaType ?? "application/octet-stream"};base64,${p.raw ?? ""}`;
}

/** Decoded byte length of a base64 string. */
export function base64Size(b64: string): number {
  const padding = b64.endsWith("==") ? 2 : b64.endsWith("=") ? 1 : 0;
  return Math.floor((b64.length * 3) / 4) - padding;
}

/** Human-readable byte size. */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

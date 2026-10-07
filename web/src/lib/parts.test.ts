import { describe, expect, it } from "vitest";
import { base64Size, dataUrl, formatBytes, joinText, partKind } from "./parts";

describe("parts helpers", () => {
  it("identifies part kinds", () => {
    expect(partKind({ text: "" })).toBe("text");
    expect(partKind({ raw: "AA==" })).toBe("raw");
    expect(partKind({ url: "u" })).toBe("url");
    expect(partKind({ data: null })).toBe("data");
    expect(partKind({})).toBe("empty");
  });
  it("joins text parts only", () => {
    expect(joinText([{ text: "a" }, { data: 1 }, { text: "b" }])).toBe("ab");
  });
  it("builds data URLs and sizes", () => {
    expect(dataUrl({ raw: "QQ==", mediaType: "text/plain" })).toBe("data:text/plain;base64,QQ==");
    expect(base64Size("QUJD")).toBe(3);
    expect(base64Size("QQ==")).toBe(1);
    expect(formatBytes(2048)).toBe("2.0 KB");
  });
});

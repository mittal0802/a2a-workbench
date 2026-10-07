import { describe, expect, it } from "vitest";
import type { TimelineEvent } from "../../lib/types";
import { mergeEvents } from "./useConversation";

describe("mergeEvents", () => {
  it("dedupes by seq and keeps order", () => {
    const e = (seq: number) => ({ seq }) as TimelineEvent;
    expect(mergeEvents([e(1), e(2)], [e(3), e(2)]).map((x) => x.seq)).toEqual([1, 2, 3]);
  });
});

import { currentTaskState } from "./useConversation";

describe("currentTaskState", () => {
  const ev = (seq: number, kind: TimelineEvent["kind"], state?: string) =>
    ({ seq, kind, data: state ? { state } : {} }) as TimelineEvent;
  it("is the latest task or status state", () => {
    expect(currentTaskState([ev(1, "user_message"), ev(2, "task", "working"), ev(3, "status", "input_required")])).toBe("input_required");
  });
  it("is submitted while the agent has not answered yet", () => {
    expect(currentTaskState([ev(1, "user_message")])).toBe("submitted");
  });
  it("is not busy after a send that failed before any task", () => {
    expect(currentTaskState([ev(1, "user_message"), ev(2, "error")])).toBeNull();
  });
  it("keeps the previous state when an error follows it", () => {
    expect(currentTaskState([ev(1, "task", "completed"), ev(2, "error")])).toBe("completed");
  });
});

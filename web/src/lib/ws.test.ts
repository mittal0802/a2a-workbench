import { afterEach, describe, expect, it, vi } from "vitest";
import { Hub } from "./ws";

class FakeSocket {
  static instances: FakeSocket[] = [];
  sent: string[] = [];
  onopen?: () => void;
  onmessage?: (e: { data: string }) => void;
  onclose?: () => void;
  readyState = 0;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(d: string) {
    this.sent.push(d);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
}

afterEach(() => {
  FakeSocket.instances = [];
  vi.useRealTimers();
});

describe("Hub", () => {
  it("re-subscribes after reconnect from the last seen seq", async () => {
    vi.useFakeTimers();
    const hub = new Hub("ws://x/ws", FakeSocket as unknown as typeof WebSocket);
    const got: number[] = [];
    hub.subscribe("conversation:c", 0, (m) => got.push((m.event as { seq: number }).seq));
    const s1 = FakeSocket.instances[0];
    s1.open();
    expect(JSON.parse(s1.sent[0])).toEqual({ op: "subscribe", topic: "conversation:c", after_seq: 0 });
    s1.onmessage?.({ data: JSON.stringify({ topic: "conversation:c", type: "event", event: { seq: 4 } }) });
    s1.close();
    await vi.advanceTimersByTimeAsync(1000);
    const s2 = FakeSocket.instances[1];
    s2.open();
    expect(JSON.parse(s2.sent[0]).after_seq).toBe(4);
    expect(got).toEqual([4]);
  });

  it("unsubscribes when the last handler leaves", () => {
    const hub = new Hub("ws://x/ws", FakeSocket as unknown as typeof WebSocket);
    const off = hub.subscribe("exchanges:c", 0, () => {});
    const s = FakeSocket.instances[0];
    s.open();
    off();
    expect(JSON.parse(s.sent[s.sent.length - 1])).toEqual({ op: "unsubscribe", topic: "exchanges:c" });
  });

  it("ignores messages for other topics", () => {
    const hub = new Hub("ws://x/ws", FakeSocket as unknown as typeof WebSocket);
    const handler = vi.fn();
    hub.subscribe("conversation:a", 0, handler);
    const s = FakeSocket.instances[0];
    s.open();
    s.onmessage?.({ data: JSON.stringify({ topic: "conversation:b", type: "event", event: { seq: 1 } }) });
    expect(handler).not.toHaveBeenCalled();
  });
});

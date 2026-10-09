export type HubMessage = { topic: string; type: string; [k: string]: unknown };
type Sub = { topic: string; lastSeq: number; handlers: Set<(m: HubMessage) => void> };

/** WebSocket client that multiplexes topic subscriptions and resumes after reconnects. */
export class Hub {
  private socket: WebSocket | null = null;
  private subs = new Map<string, Sub>();
  private retry = 0;

  constructor(
    private url: string,
    private Socket: typeof WebSocket = WebSocket,
  ) {}

  /** Receive messages of `topic` (events after `afterSeq`); returns an unsubscribe function. */
  subscribe(topic: string, afterSeq: number, handler: (m: HubMessage) => void): () => void {
    let sub = this.subs.get(topic);
    if (!sub) {
      sub = { topic, lastSeq: afterSeq, handlers: new Set() };
      this.subs.set(topic, sub);
      this.sendSubscribe(sub);
    }
    sub.handlers.add(handler);
    this.ensure();
    const current = sub;
    return () => {
      current.handlers.delete(handler);
      if (current.handlers.size === 0 && this.subs.get(topic) === current) {
        this.subs.delete(topic);
        this.send({ op: "unsubscribe", topic });
      }
    };
  }

  private ensure() {
    if (this.socket) return;
    const socket = new this.Socket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      this.retry = 0;
      for (const sub of this.subs.values()) this.sendSubscribe(sub);
    };
    socket.onmessage = (e: MessageEvent) => {
      const msg = JSON.parse(String(e.data)) as HubMessage;
      const sub = this.subs.get(msg.topic);
      if (!sub) return;
      const seq = ((msg.event ?? msg.step) as { seq?: number } | undefined)?.seq;
      if (typeof seq === "number") sub.lastSeq = Math.max(sub.lastSeq, seq);
      sub.handlers.forEach((h) => h(msg));
    };
    socket.onclose = () => {
      this.socket = null;
      if (this.subs.size === 0) return;
      const delay = Math.min(1000 * 2 ** this.retry++, 10000);
      setTimeout(() => this.ensure(), delay);
    };
  }

  private sendSubscribe(sub: Sub) {
    this.send({ op: "subscribe", topic: sub.topic, after_seq: sub.lastSeq });
  }

  private send(payload: unknown) {
    if (this.socket && this.socket.readyState === 1) this.socket.send(JSON.stringify(payload));
  }
}

let shared: Hub | null = null;

/** The application-wide hub connected to this page's server. */
export function getHub(): Hub {
  if (!shared) {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    shared = new Hub(`${scheme}://${location.host}/ws`);
  }
  return shared;
}

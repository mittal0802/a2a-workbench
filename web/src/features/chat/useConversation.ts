import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { getHub } from "../../lib/ws";
import type { TimelineEvent } from "../../lib/types";

/** Union of two event lists, one entry per seq, ordered by seq. */
export function mergeEvents(a: TimelineEvent[], b: TimelineEvent[]): TimelineEvent[] {
  return [...new Map([...a, ...b].map((e) => [e.seq, e])).values()].sort((x, y) => x.seq - y.seq);
}

/** The state of the conversation's latest task, "submitted" while a send awaits its first reply. */
export function currentTaskState(events: TimelineEvent[]): string | null {
  let failed = false;
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.kind === "task" || e.kind === "status") return e.data.state as string;
    if (e.kind === "error") failed = true;
    if (e.kind === "user_message") return failed ? null : "submitted";
  }
  return null;
}

/** Live view of one conversation: stored events plus everything streamed afterwards. */
export function useConversation(conversationId: string | null) {
  const query = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.getConversation(conversationId!),
    enabled: !!conversationId,
  });
  const [live, setLive] = useState<TimelineEvent[]>([]);
  const lastSeq = query.data?.conversation.last_seq;
  const [history, setHistory] = useState<{ id: string | null; seq: number | null }>({ id: null, seq: null });
  if (conversationId && query.data && history.id !== conversationId) {
    setHistory({ id: conversationId, seq: query.data.conversation.last_seq ?? 0 });
  }

  useEffect(() => {
    setLive([]);
  }, [conversationId]);

  useEffect(() => {
    if (!conversationId || lastSeq === undefined) return;
    return getHub().subscribe(`conversation:${conversationId}`, lastSeq, (msg) => {
      if (msg.type === "event") setLive((prev) => mergeEvents(prev, [msg.event as TimelineEvent]));
    });
  }, [conversationId, lastSeq]);

  const events = useMemo(() => mergeEvents(query.data?.events ?? [], live), [query.data, live]);
  const taskState = useMemo(() => currentTaskState(events), [events]);
  const historySeq = history.id === conversationId ? history.seq : null;
  return { conversation: query.data?.conversation ?? null, events, taskState, historySeq };
}

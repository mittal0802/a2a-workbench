import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import { INTERRUPTED, RUNNING } from "../../lib/labels";
import { toPartInputs } from "../../lib/parts";
import { buildTurns } from "../../lib/timeline";
import { DEFAULT_OPTIONS } from "../../lib/types";
import type { Agent, PartInput, SendOptions } from "../../lib/types";
import { Composer } from "./Composer";
import { AgentBubble, UserBubble } from "./Turn";
import { useConversation } from "./useConversation";

/** Chat with one agent: conversation switcher, live thread and composer. */
export function ChatView({
  agent,
  prefill,
  conversationId,
  onConversationChange,
  onInspect,
  onOpenSecurity,
}: {
  onOpenSecurity?: () => void;
  agent: Agent;
  prefill?: string;
  conversationId: string | null;
  onConversationChange: (id: string | null) => void;
  onInspect?: (exchangeId: string) => void;
}) {
  const qc = useQueryClient();
  const conversations = useQuery({
    queryKey: ["conversations", agent.id],
    queryFn: () => api.listConversations(agent.id),
  });
  const [userChoseNew, setUserChoseNew] = useState(false);
  useEffect(() => {
    if (!conversationId && !userChoseNew && conversations.data?.length) onConversationChange(conversations.data[0].id);
  }, [conversationId, conversations.data, userChoseNew, onConversationChange]);

  const { events, taskState } = useConversation(conversationId);
  const turns = buildTurns(events);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [events.length]);

  const send = useMutation({
    mutationFn: async ({ parts, options }: { parts: PartInput[]; options: SendOptions }) => {
      let id = conversationId;
      if (!id) {
        id = (await api.createConversation(agent.id)).id;
        onConversationChange(id);
        setUserChoseNew(false);
      }
      await api.sendMessage(id, parts, options);
      return id;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conversations", agent.id] }),
  });
  const stop = useMutation({ mutationFn: () => api.cancel(conversationId!) });
  const resubscribe = useMutation({ mutationFn: () => api.resubscribe(conversationId!) });
  const checkStatus = useMutation({ mutationFn: () => api.checkStatus(conversationId!) });

  return (
    <div className="chat">
      <div className="convs">
        <button
          className={!conversationId ? "on" : ""}
          onClick={() => {
            setUserChoseNew(true);
            onConversationChange(null);
          }}
        >
          ＋ New conversation
        </button>
        {conversations.data?.map((c) => (
          <button key={c.id} className={c.id === conversationId ? "on" : ""} onClick={() => onConversationChange(c.id)} title={c.context_id ?? ""}>
            {c.title}
          </button>
        ))}
      </div>
      <div className="scroll">
        <div className="thread">
          {turns.length === 0 && (
            <div className="day">Send a message to start talking to {agent.name}.</div>
          )}
          {turns.map((t, i) =>
            t.kind === "user" ? (
              <UserBubble key={`u${t.event.seq}`} turn={t} />
            ) : (
              <AgentBubble
                key={`a${i}`}
                turn={t}
                agentName={agent.name}
                onInspect={onInspect}
                onSignIn={onOpenSecurity}
                onRetry={() => {
                  const prev = turns[i - 1];
                  if (prev?.kind === "user")
                    send.mutate({
                      parts: toPartInputs(prev.event.data.message?.parts ?? []),
                      options: { ...DEFAULT_OPTIONS, ...(prev.event.data.options ?? {}) },
                    });
                }}
                onContinue={() =>
                  send.mutate({ parts: [{ kind: "text", text: "I've signed in." }], options: DEFAULT_OPTIONS })
                }
                onResubscribe={() => resubscribe.mutate()}
                onCheckStatus={() => checkStatus.mutate()}
              />
            ),
          )}
          {send.isError && <div className="err">Could not send: {(send.error as Error).message}</div>}
          <div ref={bottom} />
        </div>
      </div>
      <Composer
        agent={agent}
        prefill={prefill}
        replying={!!taskState && INTERRUPTED.has(taskState)}
        busy={!!taskState && RUNNING.has(taskState)}
        onSend={(parts, options) => send.mutate({ parts, options })}
        onStop={() => conversationId && stop.mutate()}
      />
    </div>
  );
}

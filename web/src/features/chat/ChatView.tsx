import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ConfirmButton } from "../../components/ConfirmButton";
import { SignInDialog } from "../security/SignInDialog";
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
  active = true,
}: {
  agent: Agent;
  prefill?: string;
  conversationId: string | null;
  onConversationChange: (id: string | null) => void;
  onInspect?: (exchangeId: string) => void;
  active?: boolean;
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

  const { events, taskState, historySeq } = useConversation(conversationId);
  const turns = buildTurns(events);
  const [signIn, setSignIn] = useState<{ index: number; action: "retry" | "continue"; reason?: string } | null>(null);
  const [prompted, setPrompted] = useState<Set<string>>(new Set());
  const lastTurn = turns[turns.length - 1];
  const authNeed =
    lastTurn?.kind === "agent"
      ? lastTurn.error?.category === "auth"
        ? { action: "retry" as const, reason: lastTurn.error.message, key: `e${lastTurn.events.at(-1)?.seq}`, seq: lastTurn.events.at(-1)?.seq ?? 0 }
        : lastTurn.current === "auth_required"
          ? { action: "continue" as const, reason: undefined, key: `a${lastTurn.events.at(-1)?.seq}`, seq: lastTurn.events.at(-1)?.seq ?? 0 }
          : null
      : null;
  useEffect(() => {
    if (!authNeed || !active || historySeq === null || authNeed.seq <= historySeq) return;
    if (prompted.has(`${conversationId}:${authNeed.key}`)) return;
    setPrompted((p) => new Set(p).add(`${conversationId}:${authNeed.key}`));
    setSignIn({ index: turns.length - 1, action: authNeed.action, reason: authNeed.reason });
  }, [authNeed?.key, conversationId, active, historySeq]); // eslint-disable-line react-hooks/exhaustive-deps
  const retryTurn = (i: number) => {
    const prev = turns[i - 1];
    if (prev?.kind === "user")
      send.mutate({
        parts: toPartInputs(prev.event.data.message?.parts ?? []),
        options: { ...DEFAULT_OPTIONS, ...(prev.event.data.options ?? {}) },
      });
  };
  const continueTask = () => send.mutate({ parts: [{ kind: "text", text: "I've signed in." }], options: DEFAULT_OPTIONS });
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
  const removeConversation = useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ["conversations", agent.id] });
      if (id === conversationId) onConversationChange(null);
    },
  });
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
          <span key={c.id} className="conv">
            <button className={c.id === conversationId ? "on" : ""} onClick={() => onConversationChange(c.id)} title={c.context_id ?? ""}>
              {c.origin === "assistant" ? "✦ " : ""}
              {c.title}
            </button>
            <ConfirmButton label={`Delete conversation ${c.title}`} question="Delete?" onConfirm={() => removeConversation.mutate(c.id)}>
              ✕
            </ConfirmButton>
          </span>
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
                onSignIn={() =>
                  setSignIn({
                    index: i,
                    action: t.current === "auth_required" ? "continue" : "retry",
                    reason: t.error?.message,
                  })
                }
                onRetry={() => retryTurn(i)}
                onContinue={continueTask}
                onResubscribe={() => resubscribe.mutate()}
                onCheckStatus={() => checkStatus.mutate()}
              />
            ),
          )}
          {send.isError && <div className="err">Could not send: {(send.error as Error).message}</div>}
          <div ref={bottom} />
        </div>
      </div>
      <SignInDialog
        agentId={agent.id}
        agentName={agent.name}
        open={signIn !== null}
        reason={signIn?.reason}
        action={signIn?.action ?? "retry"}
        onOpenChange={(v) => !v && setSignIn(null)}
        onDone={() => {
          if (!signIn) return;
          if (signIn.action === "retry") retryTurn(signIn.index);
          else continueTask();
        }}
      />
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

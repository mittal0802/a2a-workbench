import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Avatar } from "../../components/Avatar";
import { CopyButton } from "../../components/CopyButton";
import { Switch } from "../../components/Switch";
import { api } from "../../lib/api";
import type { AssistantSession, AssistantStep, ResponseMode } from "../../lib/types";
import { getHub } from "../../lib/ws";
import { Markdown } from "../chat/PartView";
import { ProviderSettings } from "./ProviderSettings";
import { OutParts, StepCard } from "./StepCard";
import { buildThread, outputParts } from "./timeline";

const MODES: { value: ResponseMode; label: string; hint: string }[] = [
  { value: "rewrite", label: "Assistant rewrites", hint: "Agents answer the Assistant; it answers you. Their raw output stays in each step." },
  { value: "pass_through", label: "Agents speak directly", hint: "Agents' output and questions come straight to you; the Assistant keeps the context." },
];

function mergeSteps(prev: AssistantStep[], incoming: AssistantStep): AssistantStep[] {
  if (prev.some((s) => s.seq === incoming.seq)) return prev;
  return [...prev, incoming].sort((a, b) => a.seq - b.seq);
}

/** The Assistant: an LLM that calls your agents the way A2A defines a client agent, step by step. */
export function AssistantPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.listAgents });
  const providers = useQuery({ queryKey: ["assistant-providers"], queryFn: api.assistantProviders });
  const sessions = useQuery({ queryKey: ["assistant-sessions"], queryFn: api.listAssistantSessions });
  const detail = useQuery({
    queryKey: ["assistant", sessionId],
    queryFn: () => api.getAssistantSession(sessionId!),
    enabled: !!sessionId,
  });
  const [steps, setSteps] = useState<AssistantStep[]>([]);
  const [session, setSession] = useState<AssistantSession | null>(null);
  useEffect(() => {
    if (detail.data) {
      const fetched = detail.data.steps;
      setSteps((prev) => fetched.reduce(mergeSteps, prev.filter((s) => s.session_id === sessionId)));
      setSession(detail.data.session);
    } else if (!sessionId) {
      setSteps([]);
      setSession(null);
    }
  }, [detail.data, sessionId]);
  useEffect(() => {
    if (!sessionId) return;
    const after = detail.data?.steps.at(-1)?.seq ?? 0;
    return getHub().subscribe(`assistant:${sessionId}`, after, (msg) => {
      if (msg.type !== "step") return;
      const step = msg.step as AssistantStep;
      setSteps((prev) => mergeSteps(prev, step));
      if (["done", "paused", "limit", "error", "resumed", "user"].includes(step.kind)) {
        api.getAssistantSession(sessionId).then((d) => setSession(d.session)).catch(() => {});
      }
    });
  }, [sessionId, detail.data]);

  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [mode, setMode] = useState<ResponseMode>("rewrite");
  const [enabled, setEnabled] = useState<string[] | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [text, setText] = useState("");
  const activeProvider = session?.provider ?? (provider || providers.data?.find((p) => p.configured)?.provider || "anthropic");
  const providerInfo = providers.data?.find((p) => p.provider === activeProvider);
  const activeModel = session?.model ?? (model || providerInfo?.default_model || "");
  const agentIds = session?.agent_ids ?? enabled ?? (agents.data ?? []).map((a) => a.id);
  const responseMode = session?.response_mode ?? mode;

  const send = useMutation({
    mutationFn: async (message: string) => {
      let sid = sessionId;
      if (!sid) {
        const created = await api.createAssistantSession({
          provider: activeProvider,
          model: activeModel || undefined,
          response_mode: responseMode,
          agent_ids: agentIds,
          title: message.slice(0, 80),
        });
        sid = created.id;
        qc.invalidateQueries({ queryKey: ["assistant-sessions"] });
        navigate(`/assistant/${sid}`);
      }
      await api.sendAssistantMessage(sid, message);
      return sid;
    },
  });
  const patch = useMutation({
    mutationFn: (body: { response_mode?: ResponseMode; agent_ids?: string[] }) => api.patchAssistantSession(sessionId!, body),
    onSuccess: (s) => setSession(s),
  });
  const resume = useMutation({ mutationFn: () => api.resumeAssistantSession(sessionId!) });
  const stop = useMutation({ mutationFn: () => api.stopAssistantSession(sessionId!) });

  const thread = useMemo(() => buildThread(steps), [steps]);
  const pending = session?.pending;
  const running = session?.status === "running" || send.isPending;
  const replyingTo = session?.status === "awaiting_user" ? pending?.agent : null;
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scroller.current?.scrollTo?.({ top: scroller.current.scrollHeight });
  }, [steps.length]);

  const setResponseMode = (v: ResponseMode) => (sessionId ? patch.mutate({ response_mode: v }) : setMode(v));
  const toggleAgent = (id: string, on: boolean) => {
    const next = on ? [...agentIds, id] : agentIds.filter((x) => x !== id);
    if (sessionId) patch.mutate({ agent_ids: next });
    else setEnabled(next);
  };
  const submit = () => {
    const t = text.trim();
    if (!t || running) return;
    setText("");
    send.mutate(t);
  };

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <div className="chat">
        <div className="head" style={{ paddingBottom: 14, borderBottom: "1px solid var(--line)" }}>
          <div className="emoji" style={{ width: 36, height: 36, background: "var(--brand-soft)", color: "var(--brand)" }}>
            ✦
          </div>
          <div>
            <h1>Assistant</h1>
            <div className="no" style={{ fontSize: 12.5 }}>
              Ask for anything. It works out which of your agents to call.
            </div>
          </div>
          <div className="spacer" />
          <div className="seg" role="group" aria-label="Response mode">
            {MODES.map((m) => (
              <button key={m.value} className={responseMode === m.value ? "on" : ""} title={m.hint} onClick={() => setResponseMode(m.value)}>
                {m.label}
              </button>
            ))}
          </div>
          <button className="conn" onClick={() => setSettingsOpen(true)} aria-label="Model and API key">
            Model <b>{activeModel || "choose…"}</b>
          </button>
        </div>
        {!session && providers.data && (
          <div className="thread" style={{ paddingBottom: 0 }}>
            <div className="opt" style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <label className="lbl2" style={{ fontSize: 12.5 }}>
                Provider
                <select className="jsonedit" style={{ minHeight: 0 }} value={activeProvider} onChange={(e) => { setProvider(e.target.value); setModel(""); }}>
                  {(providers.data ?? []).map((p) => (
                    <option key={p.provider} value={p.provider}>
                      {p.provider}
                      {p.configured ? "" : " (no key)"}
                    </option>
                  ))}
                </select>
              </label>
              <label className="lbl2" style={{ fontSize: 12.5 }}>
                Model
                <input className="jsonedit" style={{ minHeight: 0 }} value={model} placeholder={providerInfo?.default_model ?? "model name"} onChange={(e) => setModel(e.target.value)} />
              </label>
            </div>
            {providerInfo && !providerInfo.configured && (
              <div className="note warn">
                No API key for {activeProvider} yet.{" "}
                <button className="try" onClick={() => setSettingsOpen(true)}>
                  Add a key
                </button>
              </div>
            )}
          </div>
        )}
        <div className="scroll" ref={scroller}>
          <div className="thread">
            {thread.map((item, i) => {
              if (item.type === "user")
                return (
                  <div className="msg mine" key={i}>
                    <div className="bubble">
                      {item.step.data.to_agent && <div className="no" style={{ fontSize: 11.5 }}>to {item.step.data.to_agent}</div>}
                      <div className="whitespace-pre-wrap">{item.step.data.text}</div>
                    </div>
                  </div>
                );
              if (item.type === "think")
                return (
                  <div className="think" key={i}>
                    <Markdown text={item.step.data.text} />
                  </div>
                );
              if (item.type === "call")
                return (
                  <div key={i}>
                    <StepCard call={item.call} result={item.result} rejected={item.rejected} />
                    {item.outputs.length > 0 && <AgentSays name={item.outputs[0].data.agent} outputs={item.outputs} />}
                  </div>
                );
              if (item.type === "agent") return <AgentSays key={i} name={item.agent} outputs={item.outputs} />;
              if (item.type === "pause") {
                const d = item.step.data;
                const live = session?.status === (d.reason === "auth_required" ? "awaiting_sign_in" : "awaiting_user") && i === thread.length - 1;
                return (
                  <div className="note warn" key={i} style={{ display: "block" }}>
                    <b>{d.agent}</b> {d.reason === "auth_required" ? "needs you to sign in" : "is asking you"}:
                    <Markdown text={d.question ?? ""} />
                    {d.reason === "auth_required" && live && (
                      <div className="chips">
                        <Link className="chipbtn" to={`/agents/${d.agent_id}/security`}>
                          Sign in
                        </Link>
                        <button className="chipbtn" onClick={() => resume.mutate()}>
                          Continue
                        </button>
                      </div>
                    )}
                    {d.reason === "input_required" && live && <small>Your next message goes straight to {d.agent}.</small>}
                  </div>
                );
              }
              if (item.type === "final")
                return (
                  <div className="msg" key={i}>
                    <div className="who" style={{ background: "var(--brand-soft)", color: "var(--brand)" }}>
                      ✦
                    </div>
                    <div className="bubble final" style={{ flex: 1, minWidth: 0 }}>
                      <div className="name" style={{ display: "flex", alignItems: "center" }}>
                        <span>Assistant</span>
                        <span className="spacer" />
                        <CopyButton text={() => item.step.data.text ?? ""} label="Copy raw" className="ib copyraw" />
                      </div>
                      <Markdown text={item.step.data.text ?? ""} />
                    </div>
                  </div>
                );
              const d = item.step.data;
              return (
                <div key={i} className={item.step.kind === "resumed" ? "no" : "note bad"} style={{ display: "block", fontSize: 12.5 }}>
                  {item.step.kind === "resumed"
                    ? `Continuing after sign-in for ${d.agent}…`
                    : item.step.kind === "limit"
                      ? d.limit === "stopped"
                        ? "Stopped."
                        : `Stopped: limit reached (${d.limit}${d.value !== undefined ? ` = ${d.value}` : ""}).`
                      : d.message}
                </div>
              );
            })}
            {send.isError && <div className="err">{(send.error as Error).message}</div>}
          </div>
        </div>
        <div className="composer">
          <div className="cbox">
            <textarea
              placeholder={replyingTo ? `Reply to ${replyingTo}…` : "Ask the assistant…"}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            <div className="cbar">
              <span className="no" style={{ fontSize: 12.5, paddingLeft: 8 }}>
                Using {agentIds.length} agent{agentIds.length === 1 ? "" : "s"}
              </span>
              <div className="spacer" />
              {running && sessionId ? (
                <button className="btn" onClick={() => stop.mutate()}>
                  Stop
                </button>
              ) : (
                <button className="send" aria-label="Send" onClick={submit} disabled={!text.trim()} />
              )}
            </div>
          </div>
        </div>
      </div>
      <aside className="tools">
        <h4>Agents it can use</h4>
        <p>Turn agents on or off for this chat.</p>
        {(agents.data ?? []).map((a) => (
          <div className="toolrow" key={a.id}>
            <Avatar name={a.name} size={28} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="nm">{a.name}</div>
              <small>
                {(a.card.skills ?? []).length} skill{(a.card.skills ?? []).length === 1 ? "" : "s"}
              </small>
            </div>
            <Switch checked={agentIds.includes(a.id)} onCheckedChange={(v) => toggleAgent(a.id, v)} label={`Use ${a.name}`} />
          </div>
        ))}
        <h4 style={{ marginTop: 18 }}>Chats</h4>
        <Link className="add" to="/assistant" style={{ display: "flex" }}>
          <span>+</span>New chat
        </Link>
        {(sessions.data ?? []).map((s) => (
          <Link key={s.id} to={`/assistant/${s.id}`} className={`agent ${s.id === sessionId ? "on" : ""}`} style={{ display: "block", padding: "6px 8px" }}>
            <div className="nm" style={{ fontSize: 13 }}>{s.title}</div>
            <div className="sub">{s.status.replace("_", " ")}</div>
          </Link>
        ))}
      </aside>
      <ProviderSettings open={settingsOpen} onOpenChange={setSettingsOpen} provider={activeProvider} info={providerInfo} />
    </div>
  );
}

/** An agent's own output shown verbatim (pass-through mode), with its raw text copyable. */
function AgentSays({ name, outputs }: { name: string; outputs: AssistantStep[] }) {
  const parts = outputParts(outputs);
  const raw = parts.filter((p) => p.kind === "text").map((p) => p.text).join("\n\n");
  return (
    <div className="msg">
      <Avatar name={name} size={32} />
      <div className="bubble" style={{ flex: 1, minWidth: 0 }}>
        <div className="name" style={{ display: "flex", alignItems: "center" }}>
          <span>{name}</span>
          <span className="spacer" />
          {raw && <CopyButton text={() => raw} label="Copy raw" className="ib copyraw" />}
        </div>
        <OutParts parts={parts} />
      </div>
    </div>
  );
}

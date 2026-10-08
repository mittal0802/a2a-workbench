import { useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Avatar } from "../../components/Avatar";
import { api } from "../../lib/api";
import { AboutView } from "../about/AboutView";
import { ChatView } from "../chat/ChatView";
import { InspectDrawer } from "../inspect/InspectDrawer";
import { TasksView } from "../tasks/TasksView";
import { ConnectionMenu } from "./ConnectionMenu";

const TABS = [
  { id: "chat", label: "Chat" },
  { id: "tasks", label: "Tasks" },
  { id: "about", label: "About" },
] as const;

/** One agent: header with connection settings, and its tabs. */
export function AgentPage() {
  const { agentId = "", tab = "chat" } = useParams();
  const navigate = useNavigate();
  const agent = useQuery({ queryKey: ["agent", agentId], queryFn: () => api.getAgent(agentId) });
  const [prefill, setPrefill] = useState<string | undefined>();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [focusExchange, setFocusExchange] = useState<string | undefined>();
  const [shownAgent, setShownAgent] = useState(agentId);
  if (shownAgent !== agentId) {
    setShownAgent(agentId);
    setConversationId(null);
    setPrefill(undefined);
  }
  const changeConversation = useCallback((id: string | null) => setConversationId(id), []);
  const inspect = useCallback((exchangeId: string) => {
    setFocusExchange(exchangeId);
    setInspecting(true);
  }, []);

  if (agent.isError) return <div className="empty">This agent no longer exists.</div>;
  if (!agent.data) return <div className="empty">Loading…</div>;
  const a = agent.data;
  return (
    <>
      <div className="head">
        <Avatar name={a.name} size={36} />
        <h1>{a.name}</h1>
        <span className="status">
          <i />
          Connected
        </span>
        <div className="spacer" />
        <ConnectionMenu agent={a} />
        <button className="btn" onClick={() => setInspecting(!inspecting)} aria-pressed={inspecting}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M16 18l6-6-6-6M8 6l-6 6 6 6" />
          </svg>
          Inspect
        </button>
      </div>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <Link
            key={t.id}
            to={`/agents/${a.id}/${t.id}`}
            role="tab"
            aria-selected={tab === t.id}
            className={`tab ${tab === t.id ? "on" : ""}`}
          >
            {t.label}
          </Link>
        ))}
      </div>
      <div className="body">
        <section className={`view ${tab === "chat" ? "on" : ""}`}>
          <ChatView
            agent={a}
            prefill={prefill}
            conversationId={conversationId}
            onConversationChange={changeConversation}
            onInspect={inspect}
          />
          <InspectDrawer
            conversationId={conversationId}
            open={inspecting}
            onClose={() => setInspecting(false)}
            focusExchangeId={focusExchange}
          />
        </section>
        {tab === "tasks" && (
          <section className="view on">
            <TasksView agent={a} />
          </section>
        )}
        <section className={`view ${tab === "about" ? "on" : ""}`}>
          <AboutView
            agent={a}
            onTry={(text) => {
              setPrefill(text);
              navigate(`/agents/${a.id}/chat`);
            }}
          />
        </section>
      </div>
    </>
  );
}

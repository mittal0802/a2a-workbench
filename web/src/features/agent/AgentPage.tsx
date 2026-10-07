import { useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Avatar } from "../../components/Avatar";
import { api } from "../../lib/api";
import { AboutView } from "../about/AboutView";
import { ChatView } from "../chat/ChatView";
import { ConnectionMenu } from "./ConnectionMenu";

const TABS = [
  { id: "chat", label: "Chat" },
  { id: "about", label: "About" },
] as const;

/** One agent: header with connection settings, and its tabs. */
export function AgentPage() {
  const { agentId = "", tab = "chat" } = useParams();
  const navigate = useNavigate();
  const agent = useQuery({ queryKey: ["agent", agentId], queryFn: () => api.getAgent(agentId) });
  const [prefill, setPrefill] = useState<string | undefined>();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [shownAgent, setShownAgent] = useState(agentId);
  if (shownAgent !== agentId) {
    setShownAgent(agentId);
    setConversationId(null);
    setPrefill(undefined);
  }
  const changeConversation = useCallback((id: string | null) => setConversationId(id), []);

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
          <ChatView agent={a} prefill={prefill} conversationId={conversationId} onConversationChange={changeConversation} />
        </section>
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

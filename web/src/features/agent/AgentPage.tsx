import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { Avatar } from "../../components/Avatar";
import { api } from "../../lib/api";
import { AboutView } from "../about/AboutView";
import { ConnectionMenu } from "./ConnectionMenu";

const TABS = [{ id: "about", label: "About" }] as const;

/** One agent: header with connection settings, and its tabs. */
export function AgentPage() {
  const { agentId = "", tab = "about" } = useParams();
  const agent = useQuery({ queryKey: ["agent", agentId], queryFn: () => api.getAgent(agentId) });
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
          <Link key={t.id} to={`/agents/${a.id}/${t.id}`} role="tab" aria-selected={tab === t.id} className={`tab ${tab === t.id ? "on" : ""}`}>
            {t.label}
          </Link>
        ))}
      </div>
      <div className="body">
        <section className="view on">
          <AboutView agent={a} onTry={() => {}} />
        </section>
      </div>
    </>
  );
}

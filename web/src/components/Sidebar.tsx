import { useQuery } from "@tanstack/react-query";
import { NavLink } from "react-router";
import { api } from "../lib/api";
import { Avatar } from "./Avatar";
import { ThemeToggle } from "./ThemeToggle";

const DOT: Record<string, string> = {
  verified: "var(--green)",
  unsigned: "var(--green)",
  unverifiable: "var(--amber)",
  invalid: "var(--red)",
};

/** Left navigation: registered agents, the connect button and the theme switch. */
export function Sidebar({ onConnect }: { onConnect: () => void }) {
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.listAgents });
  return (
    <aside className="side">
      <div className="brand">
        <div className="logo">A2A</div>
        <b>A2A Workbench</b>
      </div>
      <div className="group">
        Your agents
        <button onClick={onConnect} title="Connect an agent" aria-label="Add agent">
          +
        </button>
      </div>
      <nav className="agents" aria-label="Agents">
        {agents.data?.map((a) => (
          <NavLink key={a.id} to={`/agents/${a.id}`} className={({ isActive }) => `agent ${isActive ? "on" : ""}`}>
            <Avatar name={a.name} />
            <div style={{ minWidth: 0 }}>
              <div className="nm">{a.name}</div>
              <div className="sub" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {a.card.provider?.organization ?? new URL(a.base_url).host}
              </div>
            </div>
            <span className="st" style={{ background: DOT[a.signature_status] }} title={a.signature_status} />
          </NavLink>
        ))}
        <button className="add" onClick={onConnect}>
          <span>+</span>Connect an agent
        </button>
      </nav>
      <div className="foot">
        <div className="me" aria-hidden>
          ⌂
        </div>
        <div style={{ fontSize: 13, fontWeight: 500 }}>Local workspace</div>
        <ThemeToggle />
      </div>
    </aside>
  );
}

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
      <NavLink to="/assistant" className={({ isActive }) => `nav ${isActive ? "on" : ""}`}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
          <path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15.5l-1.9-4.6L5.5 9l4.6-1.4z" />
          <path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" />
        </svg>
        Assistant
      </NavLink>
      <NavLink to="/health" className={({ isActive }) => `nav ${isActive ? "on" : ""}`}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
          <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
        </svg>
        Health checks
      </NavLink>
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
        <div style={{ fontSize: 13, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0, flex: 1 }}>
          Local
        </div>
        <NavLink to="/settings" className="ib" aria-label="Settings" title="Settings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
          </svg>
        </NavLink>
        <ThemeToggle />
      </div>
    </aside>
  );
}

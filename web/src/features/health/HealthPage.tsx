import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Avatar } from "../../components/Avatar";
import { api } from "../../lib/api";
import type { HealthRun } from "../../lib/types";

/** The newest run of each agent, from runs ordered newest first. */
export function latestByAgent(runs: HealthRun[]): Map<string, HealthRun> {
  const out = new Map<string, HealthRun>();
  for (const r of runs) if (!out.has(r.agent_id)) out.set(r.agent_id, r);
  return out;
}

/** Every agent with the score and findings of its latest health check. */
export function HealthPage() {
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.listAgents });
  const runs = useQuery({ queryKey: ["health-runs", "all"], queryFn: () => api.listHealthRuns() });
  const latest = latestByAgent(runs.data ?? []);
  return (
    <section className="page">
      <div className="wrap">
        <div className="ph">
          <div>
            <h2>Health checks</h2>
            <p>The latest conformance check of each agent. Open an agent to run a new one and read its findings.</p>
          </div>
        </div>
        {agents.data?.length === 0 && <p className="no">Connect an agent to check it.</p>}
        <div className="card">
          {(agents.data ?? []).map((a) => {
            const r = latest.get(a.id);
            return (
              <Link key={a.id} to={`/agents/${a.id}/health`} className="area" data-testid={`health-${a.id}`}>
                <Avatar name={a.name} size={28} />
                <b>{a.name}</b>
                <div className="spacer" />
                {r ? (
                  <>
                    <span className="no" style={{ fontSize: 12.5 }}>
                      {r.counts.fail ?? 0} failed · {r.counts.warn ?? 0} warnings · {new Date(r.started_at).toLocaleDateString()}
                      {r.status === "running" ? " · running" : ""}
                    </span>
                    <b style={{ width: 44, textAlign: "right" }}>{r.score ?? "–"}</b>
                  </>
                ) : (
                  <span className="no">Not checked yet</span>
                )}
              </Link>
            );
          })}
        </div>
      </div>
    </section>
  );
}

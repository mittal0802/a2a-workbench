import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import type { Agent, HealthResult, HealthRun, HealthStatus } from "../../lib/types";
import { getHub } from "../../lib/ws";
import { ExchangeDetail } from "../inspect/InspectDrawer";

const COLOR: Record<HealthStatus, string> = {
  pass: "var(--green)",
  warn: "var(--amber)",
  fail: "var(--red)",
  not_supported: "var(--line2)",
  error: "var(--muted)",
};
const LABEL: Record<HealthStatus, string> = {
  pass: "passed",
  warn: "warnings",
  fail: "failed",
  not_supported: "not supported",
  error: "could not run",
};

/** Conic-gradient stops for a gauge showing the share of each counted status. */
export function gaugeBackground(counts: HealthRun["counts"]): string {
  const order: HealthStatus[] = ["pass", "warn", "fail", "not_supported"];
  const total = order.reduce((n, k) => n + (counts[k] ?? 0), 0);
  if (!total) return "var(--line)";
  let at = 0;
  const stops = order.map((k) => {
    const from = at;
    at += ((counts[k] ?? 0) / total) * 100;
    return `${COLOR[k]} ${from}% ${at}%`;
  });
  return `conic-gradient(${stops.join(",")})`;
}

/** A one-line verdict for a finished run. */
export function headline(run: HealthRun): string {
  const fail = run.counts.fail ?? 0;
  const warn = run.counts.warn ?? 0;
  if (run.status === "running") return "Checking…";
  if (!fail && !warn) return "Healthy: every applicable check passed";
  if (!fail) return `Healthy, with ${warn} ${warn === 1 ? "suggestion" : "suggestions"}`;
  return `${fail} ${fail === 1 ? "rule" : "rules"} broken${warn ? `, ${warn} ${warn === 1 ? "suggestion" : "suggestions"}` : ""}`;
}

function Evidence({ result, onClose }: { result: HealthResult; onClose: () => void }) {
  const [selected, setSelected] = useState(result.exchange_ids[0]);
  return (
    <div className="card" style={{ marginTop: 10 }} data-testid="evidence">
      <div className="card-h">
        <b style={{ fontSize: 13 }}>Evidence: {result.exchange_ids.length} request(s)</b>
        <span className="spacer" />
        <button className="ib" onClick={onClose} aria-label="Close evidence">
          ✕
        </button>
      </div>
      <div className="card-b">
        {result.exchange_ids.length > 1 && (
          <div className="seg" style={{ marginBottom: 8, flexWrap: "wrap" }}>
            {result.exchange_ids.map((id, i) => (
              <button key={id} className={id === selected ? "on" : ""} onClick={() => setSelected(id)}>
                Request {i + 1}
              </button>
            ))}
          </div>
        )}
        {selected ? <ExchangeDetail id={selected} /> : <p className="no">This check made no request.</p>}
      </div>
    </div>
  );
}

function Issue({ r }: { r: HealthResult }) {
  const [open, setOpen] = useState(false);
  const bad = r.status === "fail";
  return (
    <div className="issue" data-testid={`issue-${r.check_id}`}>
      <div className={`sev ${bad ? "bad" : "warn"}`}>!</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h4>{r.title}</h4>
        <p>
          Expected {r.expected || "the rule to hold"}; got {r.actual || "something else"}.
          {r.interface && <span className="mono"> · {r.interface}</span>}
        </p>
        <div className="fix">
          <b>How to fix:</b> {r.fix_hint}
        </div>
        {open && <Evidence result={r} onClose={() => setOpen(false)} />}
      </div>
      <div className="act">
        <button className="btn" onClick={() => setOpen(!open)} disabled={r.exchange_ids.length === 0}>
          {open ? "Hide evidence" : "See evidence"}
        </button>
        <span className="no mono">
          {r.spec_ref} · {r.level === "must" ? "MUST" : "SHOULD"}
        </span>
      </div>
    </div>
  );
}

function Areas({ run, names }: { run: HealthRun; names: Record<string, string> }) {
  const byArea = new Map<string, HealthResult[]>();
  for (const r of run.results) byArea.set(r.area, [...(byArea.get(r.area) ?? []), r]);
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-h">By area</div>
      {[...byArea.entries()].map(([area, rs]) => {
        const counted = rs.filter((r) => r.status === "pass" || r.status === "warn" || r.status === "fail");
        const passed = rs.filter((r) => r.status === "pass").length;
        return (
          <div className="area" key={area} data-testid={`area-${area}`}>
            {names[area] ?? area}
            <div className="spacer" />
            <div className="bar" aria-hidden>
              {(["pass", "warn", "fail", "not_supported", "error"] as HealthStatus[]).map((s) => {
                const n = rs.filter((r) => r.status === s).length;
                return n ? <i key={s} style={{ width: `${(n / rs.length) * 100}%`, background: COLOR[s] }} /> : null;
              })}
            </div>
            <span className="no" style={{ width: 56, textAlign: "right" }}>
              {counted.length ? `${passed}/${counted.length}` : "n/a"}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function AllResults({ run }: { run: HealthRun }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-h">
        Every check
        <span className="spacer" />
        <button className="ib" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide" : `Show ${run.results.length}`}
        </button>
      </div>
      {open && (
        <table className="table" style={{ fontSize: 12.5 }}>
          <tbody>
            {run.results.map((r, i) => (
              <tr key={`${r.check_id}-${r.interface}-${i}`}>
                <td style={{ padding: "4px 10px", color: COLOR[r.status], whiteSpace: "nowrap" }}>{LABEL[r.status]}</td>
                <td style={{ padding: "4px 10px" }}>
                  <b>{r.check_id}</b> {r.title}
                  <div className="no">{r.actual}</div>
                </td>
                <td className="mono no" style={{ padding: "4px 10px", whiteSpace: "nowrap" }}>
                  {r.spec_ref}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Health checks of one agent: start a run, follow it live, read findings with evidence, see past runs. */
export function HealthView({ agent }: { agent: Agent }) {
  const qc = useQueryClient();
  const catalogue = useQuery({ queryKey: ["health-checks"], queryFn: api.healthChecks });
  const runs = useQuery({ queryKey: ["health-runs", agent.id], queryFn: () => api.listHealthRuns(agent.id) });
  const [runId, setRunId] = useState<string | null>(null);
  const shownId = runId ?? runs.data?.[0]?.id ?? null;
  const run = useQuery({
    queryKey: ["health-run", shownId],
    queryFn: () => api.getHealthRun(shownId!),
    enabled: !!shownId,
  });
  const [areas, setAreas] = useState<string[] | null>(null);
  const [allInterfaces, setAllInterfaces] = useState(false);
  const names = catalogue.data?.areas ?? {};
  const chosen = areas ?? Object.keys(names);

  const start = useMutation({
    mutationFn: () =>
      api.startHealthRun(agent.id, {
        areas: areas && areas.length < Object.keys(names).length ? areas : undefined,
        interfaces: allInterfaces ? "all" : "selected",
      }),
    onSuccess: ({ run_id }) => {
      setRunId(run_id);
      qc.invalidateQueries({ queryKey: ["health-runs", agent.id] });
    },
  });
  const stop = useMutation({
    mutationFn: (id: string) => api.stopHealthRun(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["health-run", shownId] }),
  });

  const running = run.data?.status === "running";
  useEffect(() => {
    if (!shownId || !running) return;
    return getHub().subscribe(`health-run:${shownId}`, 0, (msg) => {
      if (msg.type !== "progress") return;
      qc.invalidateQueries({ queryKey: ["health-run", shownId] });
      if ((msg.event as { kind?: string })?.kind === "finished") qc.invalidateQueries({ queryKey: ["health-runs", agent.id] });
    });
  }, [shownId, running, qc, agent.id]);

  const r = run.data;
  const findings = (r?.results ?? []).filter((x) => x.status === "fail" || x.status === "warn");
  findings.sort((a, b) => (a.status === b.status ? 0 : a.status === "fail" ? -1 : 1));
  const errors = (r?.results ?? []).filter((x) => x.status === "error");
  const total = catalogue.data?.checks.filter((c) => chosen.includes(c.area)).length ?? 0;

  return (
    <section className="page">
      <div className="wrap">
        <div className="ph">
          <div>
            <h2>Health</h2>
            <p>Checks {agent.name} against the A2A specification. MUST rules fail, SHOULD rules warn, and features the card doesn't declare are not counted.</p>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-b">
            <div className="note warn" style={{ marginBottom: 12 }}>
              <span className="i">!</span>
              <div>The checks send real requests: they create tasks, cancel the tasks they created, and add and delete push configs on them.</div>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }} role="group" aria-label="Areas">
              {Object.entries(names).map(([id, name]) => {
                const on = chosen.includes(id);
                return (
                  <button
                    key={id}
                    className={`tag ${on ? "on" : ""}`}
                    aria-pressed={on}
                    style={{ cursor: "pointer", opacity: on ? 1 : 0.5 }}
                    onClick={() => setAreas(on ? chosen.filter((a) => a !== id) : [...chosen, id])}
                  >
                    {id} · {name}
                  </button>
                );
              })}
            </div>
            <label className="choice" style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
              <input type="checkbox" checked={allInterfaces} onChange={(e) => setAllInterfaces(e.target.checked)} />
              Check every interface the card declares, not just the selected one
            </label>
            <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
              <button className="btn primary" onClick={() => start.mutate()} disabled={start.isPending || running || chosen.length === 0}>
                {running ? "Checking…" : r ? "Run again" : "Check health"}
              </button>
              {running && shownId && (
                <button className="btn" onClick={() => stop.mutate(shownId)}>
                  Stop
                </button>
              )}
              {running && (
                <span className="no" style={{ fontSize: 12.5 }}>
                  {r?.results.length ?? 0} results so far{total ? ` · ${total} checks selected` : ""}
                </span>
              )}
              {(start.isError || stop.isError) && <div className="err">{((start.error ?? stop.error) as Error).message}</div>}
            </div>
          </div>
        </div>

        {!r && !runs.isLoading && <p className="no">No health check has run against this agent yet.</p>}
        {r && (
          <>
            <div className="hero">
              <div className="gauge" style={{ background: gaugeBackground(r.counts) }}>
                <div>
                  <span>
                    <b data-testid="score">{r.score ?? "–"}</b>
                    <small>out of 100</small>
                  </span>
                </div>
              </div>
              <div>
                <h3>{headline(r)}</h3>
                <p>
                  {r.results.length} results over {r.interfaces.length} interface{r.interfaces.length === 1 ? "" : "s"} ·{" "}
                  {new Date(r.started_at).toLocaleString()}
                  {r.status === "stopped" ? " · stopped early" : ""}
                </p>
                <div className="stats">
                  {(["pass", "warn", "fail", "not_supported", "error"] as HealthStatus[]).map((s) => (
                    <span key={s}>
                      <i style={{ background: COLOR[s] }} />
                      {r.counts[s] ?? 0} {LABEL[s]}
                    </span>
                  ))}
                </div>
              </div>
              <div className="spacer" />
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <a className="btn" href={api.healthReportUrl(r.id, "html")}>
                  Download HTML
                </a>
                <a className="btn" href={api.healthReportUrl(r.id, "json")}>
                  Download JSON
                </a>
              </div>
            </div>

            {findings.length > 0 && (
              <div className="card" style={{ marginBottom: 14 }}>
                <div className="card-h">Fix these first</div>
                {findings.map((f, i) => (
                  <Issue key={`${f.check_id}-${f.interface}-${i}`} r={f} />
                ))}
              </div>
            )}
            {errors.length > 0 && (
              <div className="card" style={{ marginBottom: 14 }}>
                <div className="card-h">Checks that could not run (not counted)</div>
                <div className="card-b">
                  {errors.map((e, i) => (
                    <div key={`${e.check_id}-${i}`} className="row">
                      <b style={{ flex: "none" }}>{e.check_id}</b>
                      <span className="no">{e.actual}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <Areas run={r} names={names} />
            <AllResults run={r} />
          </>
        )}

        {(runs.data?.length ?? 0) > 1 && (
          <div className="card">
            <div className="card-h">Earlier runs</div>
            <div className="card-b">
              {runs.data!.map((x) => (
                <button
                  key={x.id}
                  className="row"
                  style={{ width: "100%", textAlign: "left", background: x.id === shownId ? "var(--soft)" : undefined }}
                  onClick={() => setRunId(x.id)}
                  aria-current={x.id === shownId}
                >
                  <b style={{ width: 40 }}>{x.score ?? "–"}</b>
                  <span style={{ flex: 1 }}>{new Date(x.started_at).toLocaleString()}</span>
                  <span className="no">
                    {x.counts.fail ?? 0} failed · {x.counts.warn ?? 0} warnings · {x.status}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

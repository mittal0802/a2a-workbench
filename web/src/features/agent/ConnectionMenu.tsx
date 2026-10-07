import * as Popover from "@radix-ui/react-popover";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { api } from "../../lib/api";
import { bindingLabel } from "../../lib/labels";
import type { Agent } from "../../lib/types";

/** Popover choosing which of the agent's interfaces is used, plus card refresh and removal. */
export function ConnectionMenu({ agent }: { agent: Agent }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const selected = agent.interfaces.find((i) => i.url === agent.selected_interface_url);
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["agents"] });
    qc.invalidateQueries({ queryKey: ["agent", agent.id] });
  };
  const choose = useMutation({ mutationFn: (url: string) => api.patchAgent(agent.id, url), onSuccess: invalidate });
  const refresh = useMutation({ mutationFn: () => api.refreshAgent(agent.id), onSuccess: invalidate });
  const remove = useMutation({
    mutationFn: () => api.deleteAgent(agent.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      navigate("/");
    },
  });
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button className="conn" aria-label="Connection settings">
          <b>{selected ? bindingLabel(selected.binding) : "No usable interface"}</b>
          {selected && (
            <>
              <span className="sep" />
              A2A {selected.protocol_version || "?"}
            </>
          )}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="pop on" align="end" sideOffset={8} style={{ position: "static" }}>
          <h5>How to talk to this agent</h5>
          {agent.interfaces.map((i) => (
            <button
              key={i.url}
              className="opt"
              style={{ width: "100%", textAlign: "left" }}
              disabled={!i.supported}
              onClick={() => choose.mutate(i.url)}
            >
              <div>
                {bindingLabel(i.binding)}
                {!i.supported && " (coming soon)"}
                <small>
                  {i.url} · A2A {i.protocol_version || "?"}
                </small>
              </div>
              {i.url === agent.selected_interface_url && <span className="ck">✓</span>}
            </button>
          ))}
          <h5>Agent card</h5>
          <button className="opt" style={{ width: "100%" }} onClick={() => refresh.mutate()}>
            <div>
              {refresh.isPending ? "Refreshing…" : "Refresh agent card"}
              <small>Fetch the card again from {agent.base_url}</small>
            </div>
          </button>
          <button
            className="opt"
            style={{ width: "100%", color: "var(--red)" }}
            onClick={() => {
              if (window.confirm(`Remove ${agent.name} and its conversations?`)) remove.mutate();
            }}
          >
            <div>Remove agent</div>
          </button>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

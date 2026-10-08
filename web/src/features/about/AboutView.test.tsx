import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as rtlRender, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AboutView } from "./AboutView";

const render = (ui: ReactElement) =>
  rtlRender(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);

const agent = {
  id: "1",
  name: "Zoo agent",
  base_url: "http://z",
  card_path: null,
  signature_status: "verified",
  signature_detail: null,
  selected_interface_url: "http://z/a2a",
  created_at: "",
  updated_at: "",
  interfaces: [{ url: "http://z/a2a", binding: "JSONRPC", protocol_version: "1.0", tenant: "", supported: true }],
  card: {
    name: "Zoo agent",
    description: "Reference agent",
    version: "1.0.0",
    provider: { organization: "Acme" },
    capabilities: {
      streaming: true,
      extensions: [{ uri: "https://e/x", description: "X ext", required: true }],
    },
    defaultInputModes: ["text/plain"],
    defaultOutputModes: ["application/json"],
    skills: [{ id: "echo", name: "Echo", description: "Repeats", examples: ["echo hi"], tags: ["test"] }],
  },
};

describe("AboutView", () => {
  it("renders capabilities in plain language and lets you try a skill", async () => {
    const onTry = vi.fn();
    render(<AboutView agent={agent as never} onTry={onTry} />);
    expect(screen.getByText("Reference agent")).toBeInTheDocument();
    expect(screen.getByText("Live streaming").nextSibling).toHaveTextContent("Yes");
    expect(screen.getByText("Push notifications").nextSibling).toHaveTextContent("No");
    expect(screen.getByText("https://e/x")).toBeInTheDocument();
    expect(screen.getByText("required")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try: “echo hi”/i }));
    expect(onTry).toHaveBeenCalledWith("echo hi");
  });

  it("shows the raw card on request", async () => {
    render(<AboutView agent={agent as never} onTry={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /view raw card/i }));
    expect(screen.getByText(/"defaultInputModes"/)).toBeInTheDocument();
  });
});

describe("AboutView extended card", () => {
  it("offers the extended card only when the agent declares one", async () => {
    const withExtended = { ...agent, card: { ...agent.card, capabilities: { extendedAgentCard: true } } };
    render(<AboutView agent={withExtended as never} onTry={() => {}} />);
    expect(screen.getByRole("button", { name: /load extended card/i })).toBeInTheDocument();
  });

  it("hides the extended card section otherwise", () => {
    render(<AboutView agent={agent as never} onTry={() => {}} />);
    expect(screen.queryByRole("button", { name: /load extended card/i })).toBeNull();
  });
});

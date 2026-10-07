import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../lib/api";
import { ConnectDialog } from "./ConnectDialog";

const preview = {
  card: {
    name: "Zoo agent",
    provider: { organization: "Acme" },
    skills: [{ id: "a" }],
    capabilities: { streaming: true },
  },
  signature_status: "verified",
  signature_detail: null,
  exchange_ids: [],
  default_interface_url: "http://z/a2a",
  interfaces: [
    { url: "http://z/a2a", binding: "JSONRPC", protocol_version: "1.0", tenant: "", supported: true },
    { url: "http://z/v1", binding: "HTTP+JSON", protocol_version: "1.0", tenant: "", supported: true },
    { url: "http://z/g", binding: "GRPC", protocol_version: "1.0", tenant: "", supported: false },
  ],
};

function renderDialog(onConnected = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ConnectDialog open onOpenChange={() => {}} onConnected={onConnected} />
    </QueryClientProvider>,
  );
  return onConnected;
}

describe("ConnectDialog", () => {
  it("previews the card, shows interfaces and connects", async () => {
    vi.spyOn(api, "previewCard").mockResolvedValue(preview as never);
    const add = vi.spyOn(api, "addAgent").mockResolvedValue({ id: "1", selected_interface_url: "http://z/a2a" } as never);
    const onConnected = renderDialog();
    await userEvent.type(screen.getByLabelText(/agent address/i), "http://z");
    await userEvent.click(screen.getByRole("button", { name: /find agent/i }));
    expect(await screen.findByText("Zoo agent")).toBeInTheDocument();
    expect(screen.getByText(/signed card/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /gRPC/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /JSON-RPC/ })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(add).toHaveBeenCalledWith("http://z");
    expect(onConnected).toHaveBeenCalled();
  });

  it("applies a non-default interface choice after connecting", async () => {
    vi.spyOn(api, "previewCard").mockResolvedValue(preview as never);
    vi.spyOn(api, "addAgent").mockResolvedValue({ id: "1", selected_interface_url: "http://z/a2a" } as never);
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue({ id: "1" } as never);
    renderDialog();
    await userEvent.type(screen.getByLabelText(/agent address/i), "http://z");
    await userEvent.click(screen.getByRole("button", { name: /find agent/i }));
    await userEvent.click(await screen.findByRole("radio", { name: /REST/ }));
    await userEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(patch).toHaveBeenCalledWith("1", "http://z/v1");
  });

  it("shows a friendly error when the agent cannot be reached", async () => {
    vi.spyOn(api, "previewCard").mockRejectedValue(new ApiError(422, "transport", "Could not load the agent card"));
    renderDialog();
    await userEvent.type(screen.getByLabelText(/agent address/i), "http://nope");
    await userEvent.click(screen.getByRole("button", { name: /find agent/i }));
    expect(await screen.findByText(/couldn.t reach/i)).toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { SettingsPage } from "./SettingsPage";

const providers = [
  { provider: "anthropic", configured: true, source: "stored", preview: "••••a1b2", default_model: "claude-sonnet-5-5" },
  { provider: "openai", configured: true, source: "env", preview: "••••9999", base_url: null },
  { provider: "gemini", configured: false, source: "none" },
];

function setup() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "assistantProviders").mockResolvedValue(providers as never);
});

describe("SettingsPage", () => {
  it("shows each provider's key status without the key", async () => {
    setup();
    const anthropic = await screen.findByRole("region", { name: "Anthropic" });
    expect(within(anthropic).getByText(/saved ••••a1b2/i)).toBeInTheDocument();
    const openai = screen.getByRole("region", { name: /openai/i });
    expect(within(openai).getByText(/OPENAI_API_KEY/)).toBeInTheDocument();
    const gemini = screen.getByRole("region", { name: /gemini/i });
    expect(within(gemini).getByText(/not set/i)).toBeInTheDocument();
    for (const input of screen.getAllByLabelText(/api key/i)) expect((input as HTMLInputElement).value).toBe("");
  });

  it("saves a key (with a base URL preset for OpenAI-compatible servers) and removes a saved one", async () => {
    const put = vi.spyOn(api, "putAssistantProvider").mockResolvedValue({} as never);
    const del = vi.spyOn(api, "deleteAssistantProvider").mockResolvedValue(undefined as never);
    setup();
    const openai = await screen.findByRole("region", { name: /openai/i });
    await userEvent.click(within(openai).getByRole("button", { name: "Ollama" }));
    expect(within(openai).getByLabelText(/base url/i)).toHaveValue("http://localhost:11434/v1");
    await userEvent.type(within(openai).getByLabelText(/api key/i), "ollama");
    await userEvent.click(within(openai).getByRole("button", { name: /save/i }));
    expect(put).toHaveBeenCalledWith("openai", { api_key: "ollama", base_url: "http://localhost:11434/v1" });
    const gemini = screen.getByRole("region", { name: /gemini/i });
    expect(within(gemini).queryByLabelText(/base url/i)).toBeNull();
    const anthropic = screen.getByRole("region", { name: "Anthropic" });
    await userEvent.click(within(anthropic).getByRole("button", { name: /remove saved key/i }));
    await userEvent.click(within(anthropic).getByRole("button", { name: "Remove" }));
    expect(del).toHaveBeenCalledWith("anthropic");
  });

  it("shows and hides the key being typed", async () => {
    setup();
    const gemini = await screen.findByRole("region", { name: /gemini/i });
    const input = within(gemini).getByLabelText(/api key/i);
    expect(input).toHaveAttribute("type", "password");
    await userEvent.click(within(gemini).getByRole("button", { name: /show key/i }));
    expect(input).toHaveAttribute("type", "text");
  });
});

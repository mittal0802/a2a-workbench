import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { DEFAULT_OPTIONS } from "../../lib/types";
import { Composer } from "./Composer";

const presets = [
  { name: "stable", description: "No injected failures.", rules: [], seed: 0 },
  { name: "flaky_stream", description: "The next streamed reply drops after 3 events.", rules: [{ kind: "drop_stream", params: { after_events: 3 } }], seed: 0 },
];
const agent = { card: { capabilities: { streaming: true } } } as never;

function setup(onSend = vi.fn()) {
  vi.spyOn(api, "faultPresets").mockResolvedValue(presets as never);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer agent={agent} onSend={onSend} onStop={() => {}} replying={false} busy={false} />
    </QueryClientProvider>,
  );
  return onSend;
}

describe("Network conditions", () => {
  it("applies a preset to sent messages and shows a banner", async () => {
    const onSend = setup();
    await userEvent.click(screen.getByRole("button", { name: /options/i }));
    await userEvent.click(await screen.findByRole("radio", { name: /flaky stream/i }));
    await userEvent.keyboard("{Escape}");
    expect(screen.getByText(/network conditions: flaky stream/i)).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText(/message/i), "go{Enter}");
    expect(onSend.mock.calls[0][1].faults.rules[0].kind).toBe("drop_stream");
  });

  it("turns injected failures off from the banner", async () => {
    const onSend = setup();
    await userEvent.click(screen.getByRole("button", { name: /options/i }));
    await userEvent.click(await screen.findByRole("radio", { name: /flaky stream/i }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: /turn off/i }));
    await userEvent.type(screen.getByPlaceholderText(/message/i), "go{Enter}");
    expect(onSend.mock.calls[0][1]).toEqual(DEFAULT_OPTIONS);
  });

  it("accepts a custom profile and rejects invalid JSON", async () => {
    const onSend = setup();
    await userEvent.click(screen.getByRole("button", { name: /options/i }));
    await userEvent.click(await screen.findByRole("radio", { name: /custom/i }));
    const box = screen.getByLabelText(/custom fault profile/i);
    await userEvent.type(box, "{{bad");
    expect(screen.getByText(/not a valid profile/i)).toBeInTheDocument();
    await userEvent.clear(box);
    await userEvent.type(box, '{{"rules":[[{{"kind":"refuse"}]}');
    await userEvent.keyboard("{Escape}");
    await userEvent.type(screen.getByPlaceholderText(/message/i), "go{Enter}");
    expect(onSend.mock.calls[0][1].faults.rules[0].kind).toBe("refuse");
  });
});

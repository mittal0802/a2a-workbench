import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { InspectDrawer, curlFor, exchangeExport, friendlyOperation } from "./InspectDrawer";

const summary = {
  id: "e1", operation: "send_message", http_method: "POST", url: "http://z/a2a", started_at: "",
  status: 200, duration_ms: 12, error: null, frame_count: 1,
};
const record = {
  ...summary,
  request_headers: { authorization: "••••", "content-type": "application/json" },
  request_body: '{"method":"SendStreamingMessage"}',
  response_headers: { "content-type": "text/event-stream" },
  response_body: null,
  frames: [{ t_ms: 5, data: 'data: {"result":{"task":{"id":"t"}}}' }],
  truncated: false,
};

function renderDrawer(focus?: string) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <InspectDrawer conversationId="c" open onClose={() => {}} focusExchangeId={focus} />
    </QueryClientProvider>,
  );
}

describe("InspectDrawer", () => {
  it("names operations in plain language", () => {
    expect(friendlyOperation({ operation: "send_message", frame_count: 3 } as never)).toBe("Send message (stream)");
    expect(friendlyOperation({ operation: "send_message", frame_count: 0 } as never)).toBe("Send message");
    expect(friendlyOperation({ operation: "get_agent_card", frame_count: 0 } as never)).toBe("Fetch agent card");
    expect(friendlyOperation({ operation: "cancel_task", frame_count: 0 } as never)).toBe("Stop task");
    expect(friendlyOperation({ operation: "http", http_method: "GET", url: "http://z/x/y", frame_count: 0 } as never)).toBe("GET /x/y");
  });

  it("builds a curl command keeping secrets redacted", () => {
    const cmd = curlFor(record as never);
    expect(cmd).toContain("curl -X POST 'http://z/a2a'");
    expect(cmd).toContain("-H 'authorization: ••••'");
    expect(cmd).toContain(`--data '{"method":"SendStreamingMessage"}'`);
  });

  it("exports an exchange with parsed bodies and stream events", () => {
    const out = exchangeExport(record as never);
    expect(out.request).toEqual({
      method: "POST",
      url: "http://z/a2a",
      headers: record.request_headers,
      body: { method: "SendStreamingMessage" },
    });
    expect(out.response.status).toBe(200);
    expect(out.response.events).toEqual([{ t_ms: 5, data: { result: { task: { id: "t" } } } }]);
    expect(out.response.body).toBeUndefined();
    const plain = exchangeExport({ ...record, frames: [], response_body: "not json" } as never);
    expect(plain.response.body).toBe("not json");
    expect(plain.response.events).toBeUndefined();
  });

  it("copies one exchange and exports the whole conversation", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "listExchanges").mockResolvedValue([summary]);
    vi.spyOn(api, "getExchange").mockResolvedValue(record);
    const saved: Blob[] = [];
    URL.createObjectURL = vi.fn((b: Blob) => {
      saved.push(b);
      return "blob:x";
    }) as never;
    URL.revokeObjectURL = vi.fn();
    renderDrawer("e1");
    await user.click(await screen.findByRole("button", { name: "Copy exchange" }));
    expect(JSON.parse(await navigator.clipboard.readText()).request.body).toEqual({ method: "SendStreamingMessage" });
    await user.click(screen.getByRole("button", { name: "Export all" }));
    await vi.waitFor(() => expect(saved).toHaveLength(1));
    const doc = JSON.parse(await saved[0].text());
    expect(doc.conversation_id).toBe("c");
    expect(doc.exchanges).toHaveLength(1);
    expect(doc.exchanges[0].operation).toBe("send_message");
  });

  it("shows request, SSE frames and headers of the selected exchange", async () => {
    vi.spyOn(api, "listExchanges").mockResolvedValue([summary]);
    vi.spyOn(api, "getExchange").mockResolvedValue(record);
    renderDrawer();
    await userEvent.click(await screen.findByText("Send message (stream)"));
    expect(await screen.findByText(/"SendStreamingMessage"/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Response" }));
    expect(await screen.findByText(/\+5 ms/)).toBeInTheDocument();
    expect(screen.getByText(/"task"/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Headers" }));
    expect(screen.getByText("••••")).toBeInTheDocument();
  });

  it("opens the focused exchange directly", async () => {
    vi.spyOn(api, "listExchanges").mockResolvedValue([summary]);
    const get = vi.spyOn(api, "getExchange").mockResolvedValue(record);
    renderDrawer("e1");
    expect(await screen.findByText(/"SendStreamingMessage"/)).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("e1");
  });

  it("shows transport errors of failed exchanges", async () => {
    vi.spyOn(api, "listExchanges").mockResolvedValue([{ ...summary, status: null, error: "ConnectError: refused" }]);
    vi.spyOn(api, "getExchange").mockResolvedValue({ ...record, status: null, error: "ConnectError: refused", frames: [] });
    renderDrawer("e1");
    expect(await screen.findAllByText(/ConnectError: refused/)).not.toHaveLength(0);
  });
});

describe("InspectDrawer live updates", () => {
  it("marks in-flight exchanges and recovers from a missing record", async () => {
    vi.spyOn(api, "listExchanges").mockResolvedValue([{ ...summary, complete: false, duration_ms: null }]);
    vi.spyOn(api, "getExchange").mockRejectedValue(new Error("not found"));
    renderDrawer("e1");
    expect(await screen.findByText(/in progress/i)).toBeInTheDocument();
    expect(await screen.findByText(/not recorded yet/i)).toBeInTheDocument();
  });
});

describe("InspectDrawer injected faults", () => {
  it("labels exchanges whose failure was injected", async () => {
    vi.spyOn(api, "listExchanges").mockResolvedValue([{ ...summary, fault: "drop_stream" }]);
    vi.spyOn(api, "getExchange").mockResolvedValue({ ...record, fault: "drop_stream" });
    renderDrawer();
    expect(await screen.findByText("injected: drop_stream")).toBeInTheDocument();
  });
});

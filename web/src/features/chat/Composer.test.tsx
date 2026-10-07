import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_OPTIONS } from "../../lib/types";
import { Composer } from "./Composer";

const streamingAgent = { card: { capabilities: { streaming: true }, defaultOutputModes: ["text/plain"] } } as never;

describe("Composer", () => {
  it("sends text and data parts with options on Enter", async () => {
    const onSend = vi.fn();
    render(<Composer agent={streamingAgent} onSend={onSend} onStop={() => {}} replying={false} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: /add json data/i }));
    await userEvent.type(screen.getByLabelText(/^json data$/i), '{{"n":1}');
    await userEvent.type(screen.getByPlaceholderText(/message/i), "hello{Enter}");
    expect(onSend).toHaveBeenCalledWith([{ kind: "text", text: "hello" }, { kind: "data", data: { n: 1 } }], DEFAULT_OPTIONS);
  });

  it("blocks sending invalid JSON data", async () => {
    const onSend = vi.fn();
    render(<Composer agent={streamingAgent} onSend={onSend} onStop={() => {}} replying={false} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: /add json data/i }));
    await userEvent.type(screen.getByLabelText(/^json data$/i), "{{bad");
    await userEvent.type(screen.getByPlaceholderText(/message/i), "x{Enter}");
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText(/not valid json/i)).toBeInTheDocument();
  });

  it("adds url parts", async () => {
    const onSend = vi.fn();
    render(<Composer agent={streamingAgent} onSend={onSend} onStop={() => {}} replying={false} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: /add file by url/i }));
    await userEvent.type(screen.getByLabelText(/file url/i), "https://e.com/f.pdf");
    await userEvent.type(screen.getByPlaceholderText(/message/i), "see{Enter}");
    expect(onSend.mock.calls[0][0][1]).toEqual({ kind: "file", url: "https://e.com/f.pdf" });
  });

  it("does not send empty messages and keeps shift+enter as newline", async () => {
    const onSend = vi.fn();
    render(<Composer agent={streamingAgent} onSend={onSend} onStop={() => {}} replying={false} busy={false} />);
    const box = screen.getByPlaceholderText(/message/i);
    await userEvent.type(box, "{Enter}");
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.type(box, "a{Shift>}{Enter}{/Shift}b");
    expect(box).toHaveValue("a\nb");
  });

  it("disables streaming when the agent does not support it", async () => {
    render(
      <Composer agent={{ card: { capabilities: { streaming: false } } } as never} onSend={() => {}} onStop={() => {}} replying={false} busy={false} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /options/i }));
    expect(screen.getByRole("switch", { name: /stream replies live/i })).toBeDisabled();
  });

  it("maps options menu choices into send options", async () => {
    const onSend = vi.fn();
    render(<Composer agent={streamingAgent} onSend={onSend} onStop={() => {}} replying={false} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: /options/i }));
    await userEvent.click(screen.getByRole("switch", { name: /return immediately/i }));
    await userEvent.type(screen.getByLabelText(/history to include/i), "3");
    await userEvent.type(screen.getByLabelText(/formats i accept/i), "application/json{Enter}");
    await userEvent.keyboard("{Escape}");
    await userEvent.type(screen.getByPlaceholderText(/message/i), "go{Enter}");
    expect(onSend.mock.calls[0][1]).toMatchObject({
      return_immediately: true,
      history_length: 3,
      accepted_output_modes: ["application/json"],
    });
  });

  it("shows the reply pill and stop button", () => {
    const onStop = vi.fn();
    render(<Composer agent={streamingAgent} onSend={() => {}} onStop={onStop} replying busy />);
    expect(screen.getByText(/replying to the open question/i)).toBeInTheDocument();
    screen.getByRole("button", { name: /stop task/i }).click();
    expect(onStop).toHaveBeenCalled();
  });
});

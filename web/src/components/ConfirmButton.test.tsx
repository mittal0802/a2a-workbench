import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmButton } from "./ConfirmButton";

describe("ConfirmButton", () => {
  it("asks before running the action", async () => {
    const onConfirm = vi.fn();
    render(<ConfirmButton label="Delete chat" confirmLabel="Delete" question="Delete this chat?" onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete chat" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText("Delete this chat?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText("Delete this chat?")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Delete chat" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { JsonView } from "./JsonView";

describe("JsonView copy", () => {
  it("copies the pretty-printed JSON and confirms", async () => {
    const user = userEvent.setup();
    render(<JsonView raw='{"a":1}' />);
    await user.click(screen.getByRole("button", { name: "Copy JSON" }));
    expect(await navigator.clipboard.readText()).toBe('{\n  "a": 1\n}');
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });
});

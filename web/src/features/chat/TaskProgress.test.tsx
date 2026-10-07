import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TaskProgress } from "./TaskProgress";

describe("TaskProgress", () => {
  it("shows each state once in plain language and marks the current one", () => {
    render(<TaskProgress states={["submitted", "working", "input_required"]} current="input_required" />);
    expect(screen.getByText("Received")).toBeInTheDocument();
    expect(screen.getByText("Needs your input").closest("[data-current]")).toHaveAttribute("data-current", "true");
    expect(screen.getByTitle("input_required")).toBeInTheDocument();
  });
});

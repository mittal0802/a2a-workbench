import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CardDiff, describeChange } from "./CardDiff";

describe("CardDiff", () => {
  it("describes changes in plain language", () => {
    expect(describeChange({ path: "skills[visa]", change: "added", public: null, extended: { id: "visa", name: "Visa check" } })).toBe(
      "Adds skill “Visa check”",
    );
    expect(describeChange({ path: "description", change: "changed", public: "a", extended: "b" })).toBe("Changes description");
    expect(describeChange({ path: "capabilities.extensions[u]", change: "removed", public: { uri: "u" }, extended: null })).toBe(
      "Removes capabilities.extensions[u]",
    );
  });

  it("says when there are no differences", () => {
    render(<CardDiff diff={[]} />);
    expect(screen.getByText(/identical/i)).toBeInTheDocument();
  });

  it("lists each difference", () => {
    render(<CardDiff diff={[{ path: "skills[visa]", change: "added", public: null, extended: { id: "visa", name: "Visa check" } }]} />);
    expect(screen.getByText("Adds skill “Visa check”")).toBeInTheDocument();
  });
});

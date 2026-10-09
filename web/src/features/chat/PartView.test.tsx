import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PartView } from "./PartView";

describe("PartView", () => {
  it("renders plain text preserving whitespace", () => {
    render(<PartView part={{ text: "a\nb" }} />);
    expect(screen.getByText(/a\s+b/)).toHaveClass("whitespace-pre-wrap");
  });
  it("renders markdown when media type says so", () => {
    render(<PartView part={{ text: "**bold**", mediaType: "text/markdown" }} />);
    expect(screen.getByText("bold").tagName).toBe("STRONG");
  });
  it("renders raw images inline", () => {
    render(<PartView part={{ raw: "AAAA", mediaType: "image/png", filename: "p.png" }} />);
    expect(screen.getByRole("img", { name: "p.png" })).toHaveAttribute("src", "data:image/png;base64,AAAA");
  });
  it("renders other raw files as a download", () => {
    render(<PartView part={{ raw: "AAAA", mediaType: "application/pdf", filename: "x.pdf" }} />);
    expect(screen.getByRole("link", { name: /x\.pdf/ })).toHaveAttribute("download", "x.pdf");
  });
  it("renders url parts as links", () => {
    render(<PartView part={{ url: "https://e.com/a.html", filename: "a.html" }} />);
    expect(screen.getByRole("link", { name: /a\.html/ })).toHaveAttribute("href", "https://e.com/a.html");
  });
  it("renders data parts as JSON", () => {
    render(<PartView part={{ data: { ok: true } }} />);
    expect(screen.getByText(/"ok"/)).toBeInTheDocument();
  });
  it("does not render javascript: urls as links", () => {
    render(<PartView part={{ url: "javascript:alert(1)" }} />);
    expect(screen.queryByRole("link")).toBeNull();
  });
  it("renders agent text as markdown when asked, without raw HTML", () => {
    const { container } = render(
      <PartView part={{ text: "**Bold** and a [link](https://e.com)\n\n- one\n- two <script>x</script>" }} markdown />,
    );
    expect(container.querySelector("strong")?.textContent).toBe("Bold");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("script")).toBeNull();
    const link = screen.getByRole("link", { name: "link" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });

  it("keeps a declared non-markdown text type plain even when markdown is on", () => {
    const { container } = render(<PartView part={{ text: "**x**", mediaType: "text/csv" }} markdown />);
    expect(container.querySelector("strong")).toBeNull();
  });
});

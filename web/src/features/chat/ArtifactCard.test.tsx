import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ArtifactCard } from "./ArtifactCard";

describe("ArtifactCard", () => {
  it("joins streamed text chunks before rendering markdown", () => {
    const { container } = render(
      <ArtifactCard
        complete
        artifact={{ artifactId: "a", name: "streamed", parts: [{ text: "Streaming **bo" }, { text: "ld** in " }, { text: "pieces." }] } as never}
      />,
    );
    expect(screen.getByText(/Streaming/).textContent).toBe("Streaming bold in pieces.");
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(screen.getByText(/3 parts/)).toBeInTheDocument();
  });

  it("keeps non-text parts separate", () => {
    const { container } = render(
      <ArtifactCard complete artifact={{ artifactId: "a", parts: [{ text: "a" }, { data: { n: 1 } }, { text: "b" }] } as never} />,
    );
    expect(container.querySelectorAll(".markdown")).toHaveLength(2);
  });
});

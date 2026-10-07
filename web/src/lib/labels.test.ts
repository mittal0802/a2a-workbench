import { describe, expect, it } from "vitest";
import { bindingLabel, stateLabel } from "./labels";

describe("stateLabel", () => {
  it("maps every A2A task state to plain language", () => {
    expect(stateLabel("submitted").label).toBe("Received");
    expect(stateLabel("working")).toEqual({ label: "Working", tone: "run", protocol: "working" });
    expect(stateLabel("input_required").label).toBe("Needs your input");
    expect(stateLabel("auth_required").label).toBe("Needs sign-in");
    expect(stateLabel("completed").tone).toBe("ok");
    expect(stateLabel("failed").tone).toBe("bad");
    expect(stateLabel("canceled").label).toBe("Stopped");
    expect(stateLabel("rejected").label).toBe("Declined");
    expect(stateLabel("weird").label).toBe("weird");
  });

  it("names bindings", () => {
    expect(bindingLabel("JSONRPC")).toBe("JSON-RPC");
    expect(bindingLabel("HTTP+JSON")).toBe("REST");
    expect(bindingLabel("GRPC")).toBe("gRPC");
    expect(bindingLabel("X")).toBe("X");
  });
});

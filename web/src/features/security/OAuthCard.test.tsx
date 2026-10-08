import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { OAuthCard, flowSummary } from "./OAuthCard";

const scheme = {
  name: "oauth2",
  type: "oauth2",
  label: "OAuth 2.0",
  description: "OAuth2 client_credentials flow against the Leena AI identity provider. Obtain the bot-specific client_id…",
  details: {},
  accepts: ["oauth2", "http_bearer"],
  credential: null,
  flows: ["client_credentials"],
  scopes: { "a2a:invoke": "Invoke A2A methods on the authenticated bot", "a2a:extended-card": "Fetch the audience-filtered Extended Agent Card" },
};

function setup(s = scheme) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <OAuthCard agentId="ag" scheme={s as never} requiredScopes={["a2a:invoke"]} needed />
    </QueryClientProvider>,
  );
}

describe("OAuthCard", () => {
  it("speaks plain language and keeps the agent's note tucked away", () => {
    setup();
    expect(screen.getByRole("heading", { name: "OAuth 2.0" })).toBeInTheDocument();
    expect(screen.getByText("Sign in with a client ID and secret")).toBeInTheDocument();
    expect(screen.queryByText(/clientCredentials/)).toBeNull();
    expect(screen.getByText(/note from the agent/i).closest("details")).not.toHaveAttribute("open");
  });

  it("signs in with client credentials and the required scopes preselected", async () => {
    const signIn = vi.spyOn(api, "oauthSignIn").mockResolvedValue({} as never);
    setup();
    expect(screen.getByRole("checkbox", { name: /a2a:invoke/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /a2a:extended-card/ })).not.toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: /a2a:extended-card/ }));
    await userEvent.type(screen.getByLabelText(/client id/i), "bot-1");
    await userEvent.type(screen.getByLabelText(/client secret/i), "s3cr3t");
    await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(signIn).toHaveBeenCalledWith("ag", "oauth2", {
      flow: "client_credentials",
      client_id: "bot-1",
      client_secret: "s3cr3t",
      scopes: ["a2a:invoke", "a2a:extended-card"],
      auth_method: "client_secret_post",
    });
  });

  it("shows the signed-in state with sign out", () => {
    setup({ ...scheme, credential: { scheme_name: "oauth2", kind: "oauth2", preview: "signed in · a2a:invoke", readable: true, expires_at: new Date(Date.now() + 600_000).toISOString(), updated_at: "" } } as never);
    expect(screen.getByText(/signed in · a2a:invoke/)).toBeInTheDocument();
    expect(screen.getByText(/expires in 10 min/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });

  it("describes every flow", () => {
    expect(flowSummary("authorization_code")).toBe("Sign in through your browser");
    expect(flowSummary("device_code")).toBe("Sign in with a code on another device");
    expect(flowSummary("password")).toMatch(/deprecated/);
    expect(flowSummary("implicit")).toMatch(/deprecated/);
  });
});

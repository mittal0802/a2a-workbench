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

describe("OAuthCard failures", () => {
  it("shows why sign-in failed, including the card/provider mismatch", async () => {
    const { ApiError } = await import("../../lib/api");
    vi.spyOn(api, "oauthSignIn").mockRejectedValue(
      new ApiError(422, "auth", "The token endpoint refused the request: grant_type must be one of …", {
        hint: "The provider's metadata does not list client_credentials in grant_types_supported.",
      }),
    );
    setup();
    await userEvent.type(screen.getByLabelText(/client id/i), "bot-1");
    await userEvent.type(screen.getByLabelText(/client secret/i), "s");
    await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(await screen.findByText(/token endpoint refused/i)).toBeInTheDocument();
    expect(screen.getByText(/does not list client_credentials/i)).toBeInTheDocument();
  });
});

describe("OAuthCard browser and device flows", () => {
  const browserScheme = { ...scheme, name: "oauthCode", flows: ["authorization_code"], description: "" };

  it("opens the provider's sign-in page and shows the redirect URI to register", async () => {
    const start = vi.spyOn(api, "oauthStart").mockResolvedValue({ authorize_url: "http://idp/authorize?x=1", state: "s", redirect_uri: "http://127.0.0.1:8484/oauth/callback" });
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    setup(browserScheme as never);
    expect(screen.getByText(/oauth\/callback/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/client id/i), "web-app");
    await userEvent.click(screen.getByRole("button", { name: /sign in with your browser/i }));
    expect(start).toHaveBeenCalledWith("ag", "oauthCode", { client_id: "web-app", scopes: ["a2a:invoke"] });
    expect(open).toHaveBeenCalledWith("http://idp/authorize?x=1", "a2aw-oauth", expect.any(String));
  });

  it("shows the device code and polls until signed in", async () => {
    vi.spyOn(api, "oauthDevice").mockResolvedValue({ flow_id: "f1", user_code: "ABC-123", verification_uri: "http://idp/device", verification_uri_complete: null, interval: 0, expires_in: 600 });
    const poll = vi.spyOn(api, "pollDevice").mockResolvedValueOnce({ status: "pending" }).mockResolvedValue({ status: "signed_in" });
    setup({ ...scheme, name: "oauthDevice", flows: ["device_code"], description: "" } as never);
    await userEvent.type(screen.getByLabelText(/client id/i), "tv");
    await userEvent.click(screen.getByRole("button", { name: /get a sign-in code/i }));
    expect(await screen.findByText("ABC-123")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /idp\/device/ })).toHaveAttribute("href", "http://idp/device");
    await vi.waitFor(() => expect(poll).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect(await screen.findByText(/signed in on the other device/i)).toBeInTheDocument();
  });

  it("asks to sign in again when the token could not be renewed", () => {
    setup({
      ...scheme,
      credential: {
        scheme_name: "oauth2", kind: "oauth2", preview: "signed in · a2a:invoke", readable: true,
        expires_at: "2020-01-01T00:00:00Z", updated_at: "2020-01-01T00:00:00Z",
        renewal_error: "invalid_grant: unknown refresh token",
      },
    } as never);
    expect(screen.getByText("Sign in again", { selector: ".state" })).toBeInTheDocument();
    expect(screen.getByText(/session ended and could not be renewed/i)).toBeInTheDocument();
    expect(screen.getByText(/invalid_grant: unknown refresh token/)).toBeInTheDocument();
    expect(screen.queryByText("Signed in")).toBeNull();
  });

  it("marks deprecated flows", () => {
    setup({ ...scheme, flows: ["password"], description: "" } as never);
    expect(screen.getByText(/deprecated flow/i)).toBeInTheDocument();
  });
});

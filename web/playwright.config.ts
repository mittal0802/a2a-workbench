import { defineConfig } from "@playwright/test";

const home = `${process.env.TMPDIR ?? "/tmp"}/a2aw-e2e-${process.pid}`;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  workers: 1,
  fullyParallel: false,
  use: { baseURL: "http://127.0.0.1:8585", trace: "retain-on-failure" },
  webServer: [
    {
      command: "cd ../server && uv run a2a-workbench fixtures --port 9898",
      url: "http://127.0.0.1:9898/.well-known/agent-card.json",
      reuseExistingServer: false,
    },
    {
      command: "cd ../server && uv run a2a-workbench fixtures --port 9890 --auth oauth --idp-port 9893",
      url: "http://127.0.0.1:9890/.well-known/agent-card.json",
      reuseExistingServer: false,
    },
    {
      command: "cd ../server && uv run a2a-workbench fixtures --port 9894 --auth apikey-query",
      url: "http://127.0.0.1:9894/.well-known/agent-card.json",
      reuseExistingServer: false,
    },
    {
      command: "cd ../server && uv run a2a-workbench fixtures --llm --port 9897",
      url: "http://127.0.0.1:9897/ready",
      reuseExistingServer: false,
    },
    {
      command: `rm -rf ${home} && cd ../server && A2AW_HOME=${home} uv run a2a-workbench serve --port 8585`,
      url: "http://127.0.0.1:8585/api/health",
      reuseExistingServer: false,
    },
  ],
});

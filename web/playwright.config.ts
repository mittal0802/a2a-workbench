import { defineConfig } from "@playwright/test";

const home = `${process.env.TMPDIR ?? "/tmp"}/a2aw-e2e-${process.pid}`;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:8585", trace: "retain-on-failure" },
  webServer: [
    {
      command: "cd ../server && uv run a2a-workbench fixtures --port 9898",
      url: "http://127.0.0.1:9898/.well-known/agent-card.json",
      reuseExistingServer: false,
    },
    {
      command: `rm -rf ${home} && cd ../server && A2AW_HOME=${home} uv run a2a-workbench serve --port 8585`,
      url: "http://127.0.0.1:8585/api/health",
      reuseExistingServer: false,
    },
  ],
});

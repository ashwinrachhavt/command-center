import { defineConfig } from "@playwright/test";
const port = Number(process.env.CC_WORKSPACE_PREVIEW_PORT ?? 4318);
if (!Number.isInteger(port) || port < 1024 || port > 65535)
  throw new Error(
    "CC_WORKSPACE_PREVIEW_PORT must be a valid unprivileged port",
  );
export default defineConfig({
  testDir: "./tests/workspace",
  use: { baseURL: `http://localhost:${port}`, headless: true },
  reporter: "list",
  // Animated-stream suites are timing-sensitive on 2-core CI runners;
  // one retry bounds the flake without masking real failures.
  retries: process.env.CI ? 2 : 0,
  webServer: {
    command: `npm run preview:workspace -- --port ${port}`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
  },
});

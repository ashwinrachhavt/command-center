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
  webServer: {
    command: `npm run preview:workspace -- --port ${port}`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
  },
});

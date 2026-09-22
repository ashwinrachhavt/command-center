import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testIgnore: "**/workspace/**",
  use: { baseURL: "http://127.0.0.1:4319", headless: true },
  reporter: "list",
  webServer: {
    command: "node ../../scripts/fixture_server.mjs",
    url: "http://127.0.0.1:4319/health",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});

import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/workspace",
  use: { baseURL: "http://localhost:4318", headless: true },
  reporter: "list",
  webServer: {
    command: "npm run preview:workspace",
    url: "http://localhost:4318",
    reuseExistingServer: !process.env.CI,
  },
});

import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testIgnore: "**/workspace/**",
  use: { baseURL: "http://localhost:3001", headless: true },
  reporter: "list",
});

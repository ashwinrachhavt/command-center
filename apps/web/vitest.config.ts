import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    environment: "jsdom",
    // DOM suites are CPU-heavy; unbounded forks starve interaction timers.
    maxWorkers: 4,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./tests/setup.ts"],
  },
});

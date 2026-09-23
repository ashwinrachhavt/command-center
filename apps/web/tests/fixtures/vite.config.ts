import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
    alias: {
      "@": fileURLToPath(new URL("../../src", import.meta.url)),
      "next/navigation": fileURLToPath(
        new URL("navigation.ts", import.meta.url),
      ),
      "next/link": fileURLToPath(new URL("link.tsx", import.meta.url)),
      "@clerk/nextjs": fileURLToPath(new URL("clerk.tsx", import.meta.url)),
    },
  },
  // Deferred rich views can first load in another Playwright worker. Bundle
  // their bare imports up front so Vite never reloads an active test page to
  // update its dependency graph.
  optimizeDeps: {
    include: [
      "@tiptap/react",
      "@tiptap/starter-kit",
      "@tiptap/extension-placeholder",
      "@tiptap/markdown",
      "@streamdown/cjk",
      "@streamdown/code",
      "@streamdown/math",
      "@streamdown/mermaid",
      "shiki",
      "streamdown",
      "use-stick-to-bottom",
    ],
  },
  server: { host: "localhost", port: 4318, strictPort: true },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("../../src", import.meta.url)),
      "next/navigation": fileURLToPath(
        new URL("navigation.ts", import.meta.url),
      ),
      "next/link": fileURLToPath(new URL("link.tsx", import.meta.url)),
      "@clerk/nextjs": fileURLToPath(new URL("clerk.tsx", import.meta.url)),
    },
  },
  server: { host: "localhost", port: 4318, strictPort: true },
});

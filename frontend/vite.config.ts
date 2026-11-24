/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The SPA is served under a mount path chosen at runtime (ADR-0005), so every
// asset URL must be relative. The Python side injects <base href> per request.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    outDir: fileURLToPath(new URL("../src/faststudio/static", import.meta.url)),
    emptyOutDir: true,
    sourcemap: false,
    assetsDir: "assets",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // A non-UTC zone (UTC+5, no DST), so timezone bugs cannot hide on UTC CI runners.
    env: { TZ: "Asia/Tashkent" },
  },
});

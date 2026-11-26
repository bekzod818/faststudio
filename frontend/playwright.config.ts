import { randomBytes } from "node:crypto";

import { defineConfig, devices } from "@playwright/test";

import { PASSWORD, USERNAME } from "./e2e/credentials";
import { IDLE_PORT, PORT } from "./e2e/ports";

// E2E drives the example app (examples/basic) with the built SPA through the
// real FastStudio mount, so the production CSP and security headers apply.
// --ephemeral: a throwaway database with deterministic demo data.
// The idle-timeout test also gets its own server, IDLE_PORT: tests/e2e/idle_server.py,
// a test-only launcher that injects an advanceable session clock (never packaged).
const ENV = {
  FASTSTUDIO_SECRET_KEY: randomBytes(48).toString("base64url"),
  FASTSTUDIO_EXAMPLE_ADMIN_USERNAME: USERNAME,
  FASTSTUDIO_EXAMPLE_ADMIN_PASSWORD: PASSWORD,
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}/admin/`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run python -m examples.basic --ephemeral --port ${PORT}`,
      cwd: "..",
      url: `http://127.0.0.1:${PORT}/admin/`,
      reuseExistingServer: !process.env.CI,
      env: ENV,
    },
    {
      command: `uv run python tests/e2e/idle_server.py --port ${IDLE_PORT}`,
      cwd: "..",
      url: `http://127.0.0.1:${IDLE_PORT}/admin/`,
      reuseExistingServer: !process.env.CI,
      env: ENV,
    },
  ],
});

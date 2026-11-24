import { randomBytes } from "node:crypto";

import { defineConfig, devices } from "@playwright/test";

import { PASSWORD, USERNAME } from "./e2e/credentials";

// E2E drives the example app (examples/basic) with the built SPA through the
// real FastStudio mount, so the production CSP and security headers apply.
// --ephemeral: a throwaway database with deterministic demo data.
const PORT = "4173";

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
  webServer: {
    command: `uv run python -m examples.basic --ephemeral --port ${PORT}`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/admin/`,
    reuseExistingServer: !process.env.CI,
    env: {
      FASTSTUDIO_SECRET_KEY: randomBytes(48).toString("base64url"),
      FASTSTUDIO_EXAMPLE_ADMIN_USERNAME: USERNAME,
      FASTSTUDIO_EXAMPLE_ADMIN_PASSWORD: PASSWORD,
    },
  },
});

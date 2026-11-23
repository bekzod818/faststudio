import { defineConfig, devices } from "@playwright/test";

// E2E runs the built SPA through the real FastStudio mount (scripts/e2e_server.py),
// so the production CSP and security headers apply. M12 switches to examples/basic.
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
    command: `uv run python ../scripts/e2e_server.py ${PORT}`,
    url: `http://127.0.0.1:${PORT}/admin/`,
    reuseExistingServer: !process.env.CI,
  },
});

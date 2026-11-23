import { expect, test, type Page } from "@playwright/test";

function collectProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on("pageerror", (err) => problems.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error" || /Content Security Policy/i.test(msg.text())) {
      problems.push(`console: ${msg.text()}`);
    }
  });
  return problems;
}

test("SPA renders under the admin mount with the production CSP", async ({ page }) => {
  const problems = collectProblems(page);
  const response = await page.goto("./");
  expect(response?.headers()["content-security-policy"]).toContain("script-src 'self'");
  await expect(page.getByRole("heading", { name: "FastStudio" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("deep links reload into the SPA (history fallback)", async ({ page }) => {
  const problems = collectProblems(page);
  const response = await page.goto("./models/users/42");
  expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "FastStudio" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("runtime config is injected", async ({ page }) => {
  await page.goto("./");
  const config = await page.locator("#fs-config").textContent();
  expect(JSON.parse(config ?? "{}")).toMatchObject({
    base_url: "/admin",
    api_url: "/admin/api/v1",
    schema_version: "1",
  });
});

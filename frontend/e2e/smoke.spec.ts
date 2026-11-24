import { expect, test } from "@playwright/test";

import { expectClean, signIn, watch } from "./helpers";

test("anonymous visitors land on the login page under the production CSP", async ({ page }) => {
  const state = await watch(page);
  const response = await page.goto("./");
  expect(response?.headers()["content-security-policy"]).toContain("script-src 'self'");
  await expect(page).toHaveURL(/\/admin\/login\?next=%2F$/);
  await expect(page.getByRole("heading", { level: 1, name: "FastStudio" })).toBeVisible();
  await expectClean(page, state);
});

test("signing in shows the dashboard and signing out returns to login", async ({ page }) => {
  const state = await watch(page);
  await page.goto("./");
  await signIn(page, state);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Models" })).toContainText("E2E users");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/admin\/login/);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await expectClean(page, state);
});

test("a wrong password shows a generic error", async ({ page }) => {
  const state = await watch(page, { allowLogin401: true });
  await page.goto("./login");
  await signIn(page, state, "definitely-wrong");
  await expect(page.getByRole("alert")).toContainText(/invalid/i);
  await expect(page).toHaveURL(/\/admin\/login/);
  await expectClean(page, state);
});

test("deep links survive login (history fallback + next)", async ({ page }) => {
  const state = await watch(page);
  const response = await page.goto("./models/users");
  expect(response?.status()).toBe(200);
  await expect(page).toHaveURL(/\/admin\/login\?next=%2Fmodels%2Fusers$/);
  await signIn(page, state);
  await expect(page).toHaveURL(/\/admin\/models\/users$/);
  await expect(page.getByRole("heading", { name: "E2E users" })).toBeVisible();
  await expectClean(page, state);
});

test("an expired session returns to login and back", async ({ page, context }) => {
  const state = await watch(page);
  await page.goto("./");
  await signIn(page, state);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await context.clearCookies({ name: "faststudio_session" });
  state.signedIn = false; // the next 401s are the point of this test
  await page.getByRole("link", { name: "E2E users" }).first().click();
  await page.reload();
  await expect(page).toHaveURL(/\/admin\/login\?next=%2Fmodels%2Fusers$/);
  await signIn(page, state);
  await expect(page).toHaveURL(/\/admin\/models\/users$/);
  await expectClean(page, state);
});

test("runtime config is injected", async ({ page }) => {
  await page.goto("./login");
  const config = await page.locator("#fs-config").textContent();
  expect(JSON.parse(config ?? "{}")).toMatchObject({
    base_url: "/admin",
    api_url: "/admin/api/v1",
    schema_version: "1",
  });
});

import { expect, test, type Page } from "@playwright/test";

// Test-only credentials seeded by scripts/e2e_server.py.
const USERNAME = process.env.FASTSTUDIO_E2E_USERNAME ?? "e2e-admin";
const PASSWORD = process.env.FASTSTUDIO_E2E_PASSWORD ?? "e2e-only-password";

// Runs in the page before any app script (the e2e tsconfig has no DOM types).
const RECORD_CSP_VIOLATIONS = `
  window.__cspViolations = [];
  document.addEventListener("securitypolicyviolation", (event) => {
    window.__cspViolations.push(event.violatedDirective + " " + event.blockedURI);
  });
`;

interface Watch {
  /** Problems seen so far: page errors, console errors, unexpected 401s. */
  problems: string[];
  /** 401s are expected only until we sign in (anonymous /auth/me). */
  signedIn: boolean;
}

/**
 * Record everything that should never happen. CSP violations are captured
 * with the `securitypolicyviolation` event, which also fires for blocked
 * eval/style attempts that a library catches and that never reach the console.
 */
async function watch(page: Page, { allowLogin401 = false } = {}): Promise<Watch> {
  const state: Watch = { problems: [], signedIn: false };
  await page.addInitScript({ content: RECORD_CSP_VIOLATIONS });
  page.on("pageerror", (err) => state.problems.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    // Chrome logs every 4xx response; those are judged by URL below instead.
    if (msg.type() === "error" && !/status of 401/.test(msg.text())) {
      state.problems.push(`console: ${msg.text()}`);
    }
  });
  page.on("response", (response) => {
    if (response.status() !== 401) return;
    const path = new URL(response.url()).pathname;
    const anonymousMe = !state.signedIn && path === "/admin/api/v1/auth/me";
    const failedLogin = allowLogin401 && path === "/admin/api/v1/auth/login";
    if (!anonymousMe && !failedLogin) state.problems.push(`unexpected 401: ${path}`);
  });
  return state;
}

async function expectClean(page: Page, state: Watch): Promise<void> {
  const violations: unknown = await page.evaluate("window.__cspViolations ?? []");
  expect(violations, "CSP violations").toEqual([]);
  expect(state.problems).toEqual([]);
}

async function signIn(page: Page, state: Watch, password = PASSWORD): Promise<void> {
  await page.getByLabel("Username").fill(USERNAME);
  await page.getByLabel("Password").fill(password);
  if (password === PASSWORD) state.signedIn = true;
  await page.getByRole("button", { name: "Sign in" }).click();
}

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

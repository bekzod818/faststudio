import { expect, type Page } from "@playwright/test";

// Test-only credentials seeded by scripts/e2e_server.py.
export const USERNAME = process.env.FASTSTUDIO_E2E_USERNAME ?? "e2e-admin";
export const PASSWORD = process.env.FASTSTUDIO_E2E_PASSWORD ?? "e2e-only-password";

// Runs in the page before any app script (the e2e tsconfig has no DOM types).
const RECORD_CSP_VIOLATIONS = `
  window.__cspViolations = [];
  document.addEventListener("securitypolicyviolation", (event) => {
    window.__cspViolations.push(event.violatedDirective + " " + event.blockedURI);
  });
`;

export interface Watch {
  /** Problems seen so far: page errors, console errors, unexpected 401s. */
  problems: string[];
  /** 401s are expected only until we sign in (anonymous /auth/me). */
  signedIn: boolean;
  /** Set by tests that end the session on purpose: any 401 is then expected. */
  sessionEnded: boolean;
}

/**
 * Record everything that should never happen. CSP violations are captured
 * with the `securitypolicyviolation` event, which also fires for blocked
 * eval/style attempts that a library catches and that never reach the console.
 */
export async function watch(page: Page, { allowLogin401 = false } = {}): Promise<Watch> {
  const state: Watch = { problems: [], signedIn: false, sessionEnded: false };
  await page.addInitScript({ content: RECORD_CSP_VIOLATIONS });
  page.on("pageerror", (err) => state.problems.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    // Chrome logs every 4xx response; those are judged by URL below instead.
    if (msg.type() === "error" && !/status of 401/.test(msg.text())) {
      state.problems.push(`console: ${msg.text()}`);
    }
  });
  page.on("response", (response) => {
    if (response.status() !== 401 || state.sessionEnded) return;
    const path = new URL(response.url()).pathname;
    const anonymousMe = !state.signedIn && path === "/admin/api/v1/auth/me";
    const failedLogin = allowLogin401 && path === "/admin/api/v1/auth/login";
    if (!anonymousMe && !failedLogin) state.problems.push(`unexpected 401: ${path}`);
  });
  return state;
}

export async function expectClean(page: Page, state: Watch): Promise<void> {
  const violations: unknown = await page.evaluate("window.__cspViolations ?? []");
  expect(violations, "CSP violations").toEqual([]);
  expect(state.problems).toEqual([]);
}

export async function signIn(page: Page, state: Watch, password = PASSWORD): Promise<void> {
  await page.getByLabel("Username").fill(USERNAME);
  await page.getByLabel("Password").fill(password);
  if (password === PASSWORD) state.signedIn = true;
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** A toast message (Radix also renders a hidden copy for screen readers). */
export function toastText(page: Page, text: string | RegExp) {
  return page.getByRole("region", { name: /Notifications/ }).getByText(text);
}

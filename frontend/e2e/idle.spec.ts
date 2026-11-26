import { expect, test } from "@playwright/test";

import { IDLE_PORT } from "./ports";

import { PASSWORD, USERNAME, expectClean, signIn, toastText, watch } from "./helpers";

// Runs against tests/e2e/idle_server.py: the example app with
// session_idle_timeout=60 and a session clock this test can move forward
// (a test-only launcher; FastStudio itself has no such hook).
const ORIGIN = `http://127.0.0.1:${IDLE_PORT}`;
test.use({ baseURL: `${ORIGIN}/admin/` });

test("an idle session asks to sign in and saves the original input", async ({ page }) => {
  const state = await watch(page);
  await page.goto("./models/tasks/new");
  await signIn(page, state);
  await expect(page).not.toHaveURL(/\/login/);
  const title = `Idle ${String(Date.now())}`;
  await page.getByLabel("Title").fill(title);
  await page.getByRole("button", { name: "Create task" }).click();
  await expect(page).toHaveURL(/\/models\/tasks\/items\/\d+$/);

  const edited = `${title} (edited after a break)`;
  await page.getByLabel("Title").fill(edited);
  await page.getByLabel("Notes").fill("Typed before the session expired.");
  // Two idle minutes pass (the timeout is one).
  const advanced = await page.request.post(`${ORIGIN}/__e2e__/advance?seconds=120`);
  expect(advanced.ok()).toBe(true);
  state.sessionEnded = true; // the save's 401 is expected

  await page.getByRole("button", { name: "Save changes" }).click();
  const dialog = page.getByRole("dialog", { name: "Sign in to continue" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Username")).toHaveValue(USERNAME);
  await expect(page.getByLabel("Title")).toHaveValue(edited); // still on the page
  await dialog.getByLabel("Password").fill(PASSWORD);
  await dialog.getByRole("button", { name: "Sign in and save" }).click();

  await expect(toastText(page, "Changes saved.")).toBeVisible();
  await expect(dialog).toBeHidden();
  await page.reload();
  await expect(page.getByLabel("Title")).toHaveValue(edited);
  await expect(page.getByLabel("Notes")).toHaveValue("Typed before the session expired.");
  // Nothing of the form was ever put in browser storage.
  const stored: unknown = await page.evaluate(
    "JSON.stringify([Object.keys(localStorage), Object.keys(sessionStorage)])",
  );
  expect(String(stored)).not.toContain("edited");
  await expectClean(page, state);
});

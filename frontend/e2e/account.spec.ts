import { expect, test } from "@playwright/test";

import { expectClean, signIn, watch } from "./helpers";

// ADR-0009: an admin cannot lock themselves out from their own user record.
test("own account: sign-in flags are locked and delete is hidden", async ({ page }) => {
  const state = await watch(page);
  await page.goto("./models/users");
  await signIn(page, state);
  await expect(page).not.toHaveURL(/\/login/);

  const me = await page.request.get("./api/v1/auth/me");
  const { user } = (await me.json()) as { user: { id: string } };
  await page.goto(`./models/users/items/${user.id}`);

  await expect(page.getByText(/This is your account/)).toBeVisible();
  await expect(page.getByLabel("Is active")).toBeDisabled();
  await expect(page.getByLabel("Is admin")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Delete" })).toHaveCount(0);
  await expect(page.getByLabel(/Email/)).toBeEnabled(); // the rest stays editable

  // The server is the boundary: a crafted request is refused too.
  const csrf = (await page.context().cookies()).find((c) => c.name === "faststudio_csrftoken");
  const refused = await page.request.patch(`./api/v1/models/users/items/${user.id}`, {
    data: { is_admin: false },
    headers: { "x-faststudio-csrf": csrf?.value ?? "" },
  });
  expect(refused.status()).toBe(409);
  expect(((await refused.json()) as { error: { code: string } }).error.code).toBe("self_lockout");
  expect((await page.request.get("./api/v1/auth/me")).status()).toBe(200);
  await expectClean(page, state);
});

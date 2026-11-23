import { expect, test } from "@playwright/test";

test("built SPA renders", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "FastStudio" })).toBeVisible();
  expect(errors).toEqual([]);
});

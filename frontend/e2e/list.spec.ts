import { expect, test, type Page } from "@playwright/test";

import { expectClean, signIn, watch, type Watch } from "./helpers";

// Data seeded by examples/basic (db.py): 30 products, 10 per page, ordered by id.

async function openProducts(page: Page, path = "./models/products"): Promise<Watch> {
  const state = await watch(page);
  await page.goto(path);
  await signIn(page, state);
  await expect(page.getByRole("table", { name: "Products" })).toBeVisible();
  return state;
}

function bodyRows(page: Page) {
  return page.getByRole("table", { name: "Products" }).locator("tbody tr");
}

test("lists the first page with type-aware cells", async ({ page }) => {
  const state = await openProducts(page);
  await expect(bodyRows(page)).toHaveCount(10);
  const first = bodyRows(page).first();
  await expect(first).toContainText("Widget 01");
  await expect(first).toContainText("5.99");
  await expect(first).toContainText("Hardware"); // FK label, not the id
  await expect(first).toContainText("Published");
  await expect(page.getByText("Showing 1–10 of 30")).toBeVisible();
  await expectClean(page, state);
});

test("sorts, and the sort survives a reload", async ({ page }) => {
  const state = await openProducts(page);
  await page.getByRole("button", { name: "Price" }).click();
  await page.getByRole("button", { name: "Price" }).click();
  await expect(page).toHaveURL(/ordering=-price/);
  await expect(bodyRows(page).first()).toContainText("Gadget 30");
  await page.reload();
  await expect(page.getByRole("columnheader", { name: "Price" })).toHaveAttribute(
    "aria-sort",
    "descending",
  );
  await expect(bodyRows(page).first()).toContainText("Gadget 30");
  await expectClean(page, state);
});

test("searches and filters on the server", async ({ page }) => {
  const state = await openProducts(page);
  await page.getByRole("searchbox", { name: "Search products" }).fill("widget");
  await expect(page.getByText("Showing 1–10 of 15")).toBeVisible();
  await page.getByLabel("Status").selectOption({ label: "Empty" });
  await expect(page).toHaveURL(/filter%5Bstatus%5D=null/);
  // Widgets (odd ids) with no status (id % 4 == 3): 3, 7, ..., 27.
  await expect(bodyRows(page)).toHaveCount(7);
  await page.getByLabel("In stock").selectOption({ label: "No" });
  // ...and out of stock (id % 3 == 0): 3, 15, 27.
  await expect(bodyRows(page)).toHaveCount(3);
  await page.getByRole("searchbox", { name: "Search products" }).fill("nothing-matches");
  await expect(page.getByText("No products match the current search and filters.")).toBeVisible();
  await page.getByRole("button", { name: "Clear search and filters" }).click();
  await expect(page.getByText("Showing 1–10 of 30")).toBeVisible();
  await expectClean(page, state);
});

test("paginates and the back button restores the previous page", async ({ page }) => {
  const state = await openProducts(page);
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page.getByText("Page 2 of 3")).toBeVisible();
  await expect(bodyRows(page).first()).toContainText("Widget 11");
  await page.getByRole("button", { name: "Last page" }).click();
  await expect(page.getByText("Showing 21–30 of 30")).toBeVisible();
  await expect(page.getByRole("button", { name: "Next page" })).toBeDisabled();
  await page.goBack();
  await expect(page.getByText("Page 2 of 3")).toBeVisible();
  await expectClean(page, state);
});

test("a tampered URL never reaches the server as an invalid query", async ({ page }) => {
  const state = await openProducts(page, "./models/products?page=0&ordering=secret&filter[name]=x");
  await expect(page.getByText("Showing 1–10 of 30")).toBeVisible();
  await expectClean(page, state); // no 400 or console error
});

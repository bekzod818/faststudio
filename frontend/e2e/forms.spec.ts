import { expect, test, type Page } from "@playwright/test";

import { expectClean, signIn, toastText, watch, type Watch } from "./helpers";

// Writes go to the Task model only (products stay untouched for list.spec).

function uniqueTitle(): string {
  return `Task ${String(Date.now())}-${String(Math.floor(Math.random() * 1e6))}`;
}

async function open(page: Page, path: string): Promise<Watch> {
  const state = await watch(page);
  await page.goto(path);
  await signIn(page, state);
  await expect(page).not.toHaveURL(/\/login/); // signed in before navigating on
  return state;
}

async function createTask(page: Page, title: string): Promise<string> {
  await page.goto("./models/tasks/new");
  await page.getByLabel("Title").fill(title);
  await page.getByRole("button", { name: "Create task" }).click();
  await expect(page).toHaveURL(/\/models\/tasks\/items\/\d+$/);
  return page.url();
}

test("creates a record with every widget and lands on it", async ({ page }) => {
  const state = await open(page, "./models/tasks/new");
  const title = uniqueTitle();
  await expect(page.getByRole("heading", { name: "Add task" })).toBeVisible();
  await expect(page.getByLabel("Created at")).toHaveCount(0); // readonly: not on create
  await page.getByLabel("Title").fill(title);
  await expect(page.getByText("What needs doing.")).toBeVisible(); // help text from the comment
  await page.getByLabel("Done").check();
  await page.getByLabel("Priority").fill("3");
  await page.getByLabel("Estimate").fill("12.50");
  await page.getByLabel("Due").fill("2026-12-24");
  await page.getByLabel("Status").selectOption({ label: "Published" });
  await page.getByLabel("Notes").fill("Line one\nLine two");
  const category = page.getByRole("combobox", { name: "Category" });
  await category.fill("Boo");
  await page.getByRole("option", { name: "Books" }).click();
  await expect(category).toHaveValue("Books");
  await page.getByRole("button", { name: "Create task" }).click();

  await expect(page).toHaveURL(/\/models\/tasks\/items\/\d+$/);
  await expect(toastText(page, "Task created.")).toBeVisible();
  await expect(page.getByLabel("Title")).toHaveValue(title);
  await expect(page.getByLabel("Done")).toBeChecked();
  await expect(page.getByLabel("Estimate")).toHaveValue("12.50");
  await expect(page.getByLabel("Due")).toHaveValue("2026-12-24");
  await expect(page.getByRole("combobox", { name: "Category" })).toHaveValue("Books");
  await expect(page.getByLabel("Created at")).toBeDisabled();
  await expectClean(page, state);
});

test("validates in the browser before sending", async ({ page }) => {
  const state = await open(page, "./models/tasks/new");
  let posted = false;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/models/tasks/items")) posted = true;
  });
  await page.getByLabel("Priority").fill("1.5");
  await page.getByLabel("Estimate").fill("1.234");
  await page.getByRole("button", { name: "Create task" }).click();
  await expect(page.getByText("This field is required.")).toBeVisible();
  await expect(page.getByText("Enter a whole number.")).toBeVisible();
  await expect(page.getByText("Use at most 2 decimal places.")).toBeVisible();
  await expect(page.getByLabel("Title")).toBeFocused();
  expect(posted).toBe(false);
  await expectClean(page, state);
});

test("edits only what changed and shows it in the list", async ({ page }) => {
  const state = await open(page, "./models/tasks");
  const title = uniqueTitle();
  await createTask(page, title);
  const save = page.getByRole("button", { name: "Save changes" });
  await expect(save).toBeDisabled();
  const patch = page.waitForRequest(
    (request) => request.method() === "PATCH" && request.url().includes("/models/tasks/items/"),
  );
  await page.getByLabel("Priority").fill("9");
  await save.click();
  expect((await patch).postDataJSON()).toEqual({ priority: 9 });
  await expect(toastText(page, "Changes saved.")).toBeVisible();
  await expect(save).toBeDisabled();
  await page.getByRole("main").getByRole("link", { name: "Tasks" }).click();
  await page.getByRole("searchbox", { name: "Search tasks" }).fill(title);
  const row = page.getByRole("row", { name: new RegExp(title) });
  await expect(row).toContainText("9");
  await expectClean(page, state);
});

test("guards unsaved changes", async ({ page }) => {
  const state = await open(page, "./models/tasks");
  await createTask(page, uniqueTitle());
  await page.getByLabel("Priority").fill("4");
  await page.getByRole("main").getByRole("link", { name: "Tasks" }).click();
  const dialog = page.getByRole("dialog", { name: "Leave this page?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Stay" }).click();
  await expect(page.getByLabel("Priority")).toHaveValue("4");
  await page.getByRole("main").getByRole("link", { name: "Tasks" }).click();
  await dialog.getByRole("button", { name: "Discard changes" }).click();
  await expect(page).toHaveURL(/\/models\/tasks$/);
  await expectClean(page, state);
});

test("deletes after confirmation", async ({ page }) => {
  const state = await open(page, "./models/tasks");
  const title = uniqueTitle();
  const url = await createTask(page, title);
  await page.getByRole("button", { name: "Delete" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("This cannot be undone.");
  // Centred as a modal (not stuck in a corner by the CSS reset).
  const box = await dialog.boundingBox();
  const viewport = page.viewportSize();
  expect(box && viewport).toBeTruthy();
  if (box && viewport) {
    expect(Math.abs(box.x + box.width / 2 - viewport.width / 2)).toBeLessThan(2);
    expect(Math.abs(box.y + box.height / 2 - viewport.height / 2)).toBeLessThan(2);
  }
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/models\/tasks$/);
  await expect(toastText(page, /deleted\./)).toBeVisible();
  const response = await page.request.get(
    url.replace("/admin/models/tasks/items/", "/admin/api/v1/models/tasks/items/"),
  );
  // SQLite reuses the highest deleted id, so a parallel test may already have
  // created another task under it: the deleted record must be gone either way.
  if (response.status() !== 404) {
    expect(response.status()).toBe(200);
    expect(((await response.json()) as { data: { title: string } }).data.title).not.toBe(title);
  }
  await expectClean(page, state);
});

test("a refused delete is explained and nothing changes", async ({ page }) => {
  const state = await open(page, "./models/categories/items/1");
  await expect(page.getByLabel("Name")).toHaveValue("Hardware");
  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(
    page
      .getByRole("status")
      .or(page.getByRole("alert"))
      .filter({ hasText: /related|in use|refer/i })
      .first(),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/models\/categories\/items\/1$/);
  // The refused DELETE is a 409 by design; nothing else may go wrong.
  expect(state.problems.filter((problem) => !problem.includes("409"))).toEqual([]);
});

test("signing out with unsaved changes asks first, then reaches the login page", async ({
  page,
}) => {
  const state = await open(page, "./models/tasks");
  await createTask(page, uniqueTitle());
  await page.getByLabel("Priority").fill("5");
  await page.getByRole("button", { name: "Sign out" }).click();
  const dialog = page.getByRole("dialog", { name: "Sign out?" });
  await expect(dialog).toContainText("unsaved changes");
  await dialog.getByRole("button", { name: "Stay" }).click();
  await expect(page.getByLabel("Priority")).toHaveValue("5");
  await page.getByRole("button", { name: "Sign out" }).click();
  await dialog.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/admin\/login/);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await expectClean(page, state); // no stray 401s from the signed-out page
});

test("edits many-to-many tags with the multi-select", async ({ page }) => {
  const state = await open(page, "./models/tasks");
  await createTask(page, uniqueTitle());
  const tags = page.getByRole("combobox", { name: "Tags" });
  const chips = page.getByRole("list", { name: "Selected Tags" });
  await expect(chips).toContainText("None selected.");

  // More tags than one page: scrolling the list loads the rest.
  await tags.click();
  const listbox = page.getByRole("listbox", { name: "Tags" });
  await expect(page.getByText("Showing 20 of 25. Scroll or type to see more.")).toBeVisible();
  await listbox.hover();
  await page.mouse.wheel(0, 2000);
  await expect(listbox.getByRole("option", { name: "urgent" })).toBeVisible();
  await listbox.getByRole("option", { name: "urgent" }).click();
  await expect(tags).toHaveAttribute("aria-expanded", "true"); // stays open for more

  // Keyboard: search, walk to the option, toggle it with Enter.
  await tags.fill("doc");
  await expect(listbox.getByRole("option")).toHaveCount(1);
  await tags.press("ArrowDown");
  await tags.press("Enter");
  await tags.press("Escape");
  await expect(chips.getByRole("listitem")).toHaveText(["urgent", "docs"]);

  const save = page.getByRole("button", { name: "Save changes" });
  let patch = page.waitForRequest((request) => request.method() === "PATCH");
  await save.click();
  expect((await patch).postDataJSON()).toEqual({ tags: [1, 6] });
  await expect(toastText(page, "Changes saved.")).toBeVisible();

  // Edits of other fields leave the set out of the PATCH.
  patch = page.waitForRequest((request) => request.method() === "PATCH");
  await page.getByLabel("Priority").fill("2");
  await save.click();
  expect((await patch).postDataJSON()).toEqual({ priority: 2 });

  await page.getByRole("button", { name: "Remove urgent from Tags" }).click();
  patch = page.waitForRequest((request) => request.method() === "PATCH");
  await save.click();
  expect((await patch).postDataJSON()).toEqual({ tags: [6] });
  await page.reload();
  await expect(chips.getByRole("listitem")).toHaveText(["docs"]);

  // The delete confirmation says which links go with the record.
  await page.getByRole("button", { name: "Delete" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("1 link in Tags");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expectClean(page, state);
});

import { SKIP_GUARD, hasUnsavedChanges, setUnsavedChanges, skipsGuard } from "./unsaved";

it("recognises navigations that skip the guard", () => {
  expect(skipsGuard({ ...SKIP_GUARD, signedOut: true })).toBe(true);
  expect(skipsGuard({ skipGuard: "yes" })).toBe(false);
  expect(skipsGuard(null)).toBe(false);
});

it("tracks unsaved changes per form", () => {
  setUnsavedChanges("a", true);
  setUnsavedChanges("b", true);
  setUnsavedChanges("a", false);
  expect(hasUnsavedChanges()).toBe(true);
  setUnsavedChanges("b", false);
  expect(hasUnsavedChanges()).toBe(false);
});

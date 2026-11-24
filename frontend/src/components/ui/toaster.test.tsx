import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { MAX_TOASTS, getToasts, toast } from "@/lib/toast";

import { Toaster } from "./toaster";

describe("toaster", () => {
  afterEach(() => {
    act(() => {
      toast.clear();
    });
  });

  it("shows queued messages and dismisses them", async () => {
    render(<Toaster />);
    act(() => {
      toast.error("Sign-out failed.");
    });
    expect(await screen.findByText("Sign-out failed.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(getToasts()).toHaveLength(0);
  });

  it("keeps only the newest toasts", () => {
    for (let i = 0; i < MAX_TOASTS + 2; i++) toast.info(`message ${String(i)}`);
    const messages = getToasts().map((item) => item.message);
    expect(messages).toHaveLength(MAX_TOASTS);
    expect(messages.at(-1)).toBe(`message ${String(MAX_TOASTS + 1)}`);
  });

  it("renders text, never HTML", async () => {
    render(<Toaster />);
    act(() => {
      toast.info("<img src=x onerror=alert(1)>");
    });
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
  });

  it("does not inject <style> elements (strict CSP)", () => {
    const before = document.querySelectorAll("style").length;
    render(<Toaster />);
    act(() => {
      toast.success("Saved.");
    });
    expect(document.querySelectorAll("style")).toHaveLength(before);
  });
});

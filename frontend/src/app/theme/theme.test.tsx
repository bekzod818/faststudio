import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { THEME_STORAGE_KEY } from "./theme";
import { ThemeProvider } from "./ThemeProvider";
import { ThemeToggle } from "./ThemeToggle";

describe("theme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("cycles light -> dark -> system and persists the choice", async () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    const toggle = () => userEvent.click(screen.getByRole("button", { name: /theme/i }));
    await toggle();
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    await toggle();
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    await toggle();
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    expect(screen.getByRole("button", { name: /theme: system/i })).toBeInTheDocument();
  });

  it("follows OS changes in system mode", () => {
    const listeners = new Set<() => void>();
    const query = {
      matches: false,
      addEventListener: (_: string, fn: () => void) => listeners.add(fn),
      removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
    };
    vi.stubGlobal("matchMedia", () => query);
    render(<ThemeProvider>x</ThemeProvider>);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    act(() => {
      query.matches = true;
      for (const fn of listeners) fn();
    });
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("restores the stored theme", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    act(() => {
      render(<ThemeProvider>x</ThemeProvider>);
    });
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("ignores garbage in storage", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "<script>");
    render(<ThemeProvider>x</ThemeProvider>);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});

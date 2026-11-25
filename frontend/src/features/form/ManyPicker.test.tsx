import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import type { ApiClient, GetOptions } from "@/api/client";
import type { ChoicesResponse } from "@/api/contract.gen";
import { ApiProvider } from "@/api/provider";
import { DEV_CONFIG } from "@/lib/config";
import { ConfigProvider } from "@/lib/ConfigProvider";
import { fakeClient } from "@/test/render";

import { ManyPicker } from "./ManyPicker";

const PATH = "/models/posts/fields/tags/choices";
/** 45 tags: three pages of 20, 20 and 5. */
const TAGS = Array.from({ length: 45 }, (_, index) => ({
  value: String(index + 1),
  label: `Tag ${String(index + 1).padStart(2, "0")}`,
}));

function Harness({
  initial,
  maxItems,
  disabled,
}: {
  initial: string[];
  maxItems: number | null;
  disabled: boolean;
}) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="tags">Tags</label>
      <ManyPicker
        id="tags"
        label="Tags"
        identity="posts"
        field="tags"
        value={value}
        initialLabels={{ "1": "Tag 01", "2": "Tag 02" }}
        maxItems={maxItems}
        disabled={disabled}
        onChange={setValue}
      />
      <output data-testid="value">{value.join(",")}</output>
    </>
  );
}

function setup({
  initial = ["1", "2"],
  maxItems = 500,
  disabled = false,
  maxListOffset = DEV_CONFIG.maxListOffset,
}: {
  initial?: string[];
  maxItems?: number | null;
  disabled?: boolean;
  maxListOffset?: number;
} = {}) {
  const get = vi.fn((_url: string, options?: GetOptions) => {
    const q = String(options?.params?.q ?? "").toLowerCase();
    const page = Number(options?.params?.page ?? 1);
    const found = TAGS.filter((tag) => tag.label.toLowerCase().includes(q));
    return Promise.resolve<ChoicesResponse>({
      items: found.slice((page - 1) * 20, page * 20),
      total: found.length,
    });
  });
  render(
    <ConfigProvider value={{ ...DEV_CONFIG, maxListOffset }}>
      <QueryClientProvider client={new QueryClient()}>
        <ApiProvider client={fakeClient({ get: get as unknown as ApiClient["get"] })}>
          <Harness initial={initial} maxItems={maxItems} disabled={disabled} />
        </ApiProvider>
      </QueryClientProvider>
    </ConfigProvider>,
  );
  return { get };
}

const chips = () => screen.getByRole("list", { name: "Selected Tags" });
const value = () => screen.getByTestId("value").textContent;

describe("ManyPicker", () => {
  it("shows the current items as chips and removes one with its button", async () => {
    setup();
    expect(within(chips()).getByText("Tag 01")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Remove Tag 01 from Tags" }));
    expect(value()).toBe("2");
    expect(within(chips()).queryByText("Tag 01")).toBeNull();
  });

  it("adds and removes items with the keyboard, staying open", async () => {
    setup();
    const box = screen.getByRole("combobox", { name: "Tags" });
    box.focus();
    const listbox = await screen.findByRole("listbox", { name: "Tags" });
    expect(listbox).toHaveAttribute("aria-multiselectable", "true");
    expect(await screen.findByRole("option", { name: /Tag 03/ })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
    expect(value()).toBe("1,2,3");
    expect(within(chips()).getByText("Tag 03")).toBeVisible();
    expect(box).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("option", { name: /Tag 03/ })).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Home}{Enter}"); // toggles Tag 01 off
    expect(value()).toBe("2,3");
    await userEvent.keyboard("{Escape}");
    expect(box).toHaveAttribute("aria-expanded", "false");
  });

  it("removes the last chip with Backspace in an empty input", async () => {
    setup();
    screen.getByRole("combobox", { name: "Tags" }).focus();
    await userEvent.keyboard("{Backspace}");
    expect(value()).toBe("1");
  });

  it("searches on the server and adds with the mouse", async () => {
    const { get } = setup({ initial: [] });
    expect(within(chips()).getByText("None selected.")).toBeVisible();
    await userEvent.type(screen.getByRole("combobox", { name: "Tags" }), "44");
    await waitFor(() => {
      expect(get).toHaveBeenLastCalledWith(
        PATH,
        expect.objectContaining({ params: { q: "44", page: undefined } }),
      );
    });
    await userEvent.click(await screen.findByRole("option", { name: /Tag 44/ }));
    expect(value()).toBe("44");
    expect(within(chips()).getByText("Tag 44")).toBeVisible();
  });

  it("loads further pages when scrolled to the end", async () => {
    const { get } = setup();
    await userEvent.click(screen.getByRole("combobox", { name: "Tags" }));
    expect(await screen.findByText("Showing 20 of 45. Scroll or type to see more.")).toBeVisible();
    const listbox = screen.getByRole("listbox", { name: "Tags" });
    fireEvent.scroll(listbox);
    expect(await screen.findByRole("option", { name: /Tag 40/ })).toBeInTheDocument();
    expect(get).toHaveBeenLastCalledWith(
      PATH,
      expect.objectContaining({ params: { q: undefined, page: 2 } }),
    );
    fireEvent.scroll(listbox);
    expect(await screen.findByRole("option", { name: /Tag 45/ })).toBeInTheDocument();
    fireEvent.scroll(listbox);
    expect(get).toHaveBeenCalledTimes(3); // nothing after the last page
  });

  it("loads the next page when the arrow keys reach the last option", async () => {
    setup();
    screen.getByRole("combobox", { name: "Tags" }).focus();
    await screen.findByRole("option", { name: /Tag 20/ });
    await userEvent.keyboard("{End}");
    expect(await screen.findByRole("option", { name: /Tag 21/ })).toBeInTheDocument();
  });

  it("never asks for pages beyond the server's offset cap", async () => {
    const { get } = setup({ maxListOffset: 20 });
    await userEvent.click(screen.getByRole("combobox", { name: "Tags" }));
    await screen.findByRole("option", { name: /Tag 20/ });
    fireEvent.scroll(screen.getByRole("listbox", { name: "Tags" }));
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("stops adding at max_items but still allows removing", async () => {
    setup({ maxItems: 2 });
    screen.getByRole("combobox", { name: "Tags" }).focus();
    expect(await screen.findByText("Limit reached: at most 2 can be chosen.")).toBeVisible();
    expect(screen.getByRole("option", { name: /Tag 03/ })).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(screen.getByRole("option", { name: /Tag 03/ }));
    expect(value()).toBe("1,2");
    await userEvent.click(screen.getByRole("option", { name: /Tag 02/ }));
    expect(value()).toBe("1");
  });

  it("is read-only when disabled: chips without buttons and no search box", () => {
    const { get } = setup({ disabled: true });
    expect(within(chips()).getByText("Tag 02")).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });

  it("shows unknown keys by their value", () => {
    setup({ initial: ["7"] });
    expect(within(chips()).getByText("7")).toBeVisible();
  });

  it("labels keys that arrive after mount from the record's labels", () => {
    const client = fakeClient();
    const view = (keys: string[], labels: Record<string, string>) => (
      <ConfigProvider value={DEV_CONFIG}>
        <QueryClientProvider client={new QueryClient()}>
          <ApiProvider client={client}>
            <ManyPicker
              id="tags"
              label="Tags"
              identity="posts"
              field="tags"
              value={keys}
              initialLabels={labels}
              maxItems={null}
              disabled
              onChange={() => undefined}
            />
          </ApiProvider>
        </QueryClientProvider>
      </ConfigProvider>
    );
    const { rerender } = render(view(["1"], { "1": "Tag 01" }));
    rerender(view(["1", "9"], { "1": "Tag 01", "9": "Tag 09" })); // refetched record
    expect(within(chips()).getByText("Tag 09")).toBeVisible();
  });

  it("ignores Enter while the previous search's options are still shown", async () => {
    let release: () => void = () => undefined;
    const get = vi.fn((_url: string, options?: GetOptions) => {
      const q = String(options?.params?.q ?? "");
      const items = TAGS.filter((tag) => tag.label.includes(q)).slice(0, 20);
      if (q === "") return Promise.resolve<ChoicesResponse>({ items, total: items.length });
      return new Promise<ChoicesResponse>((resolve) => {
        release = () => {
          resolve({ items, total: items.length });
        };
      });
    });
    render(
      <ConfigProvider value={DEV_CONFIG}>
        <QueryClientProvider client={new QueryClient()}>
          <ApiProvider client={fakeClient({ get: get as unknown as ApiClient["get"] })}>
            <Harness initial={[]} maxItems={null} disabled={false} />
          </ApiProvider>
        </QueryClientProvider>
      </ConfigProvider>,
    );
    const box = screen.getByRole("combobox", { name: "Tags" });
    box.focus();
    await screen.findByRole("option", { name: /Tag 01/ });
    await userEvent.type(box, "Tag 4");
    await waitFor(() => {
      expect(get).toHaveBeenCalledTimes(2); // the search is in flight, old options shown
    });
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(value()).toBe("");
    release();
    expect(await screen.findByRole("option", { name: /Tag 40/ })).toBeVisible();
    await userEvent.keyboard("{Home}{Enter}");
    expect(value()).toBe("40");
  });
});

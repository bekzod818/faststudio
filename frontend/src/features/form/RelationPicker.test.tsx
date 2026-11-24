import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import type { ApiClient, GetOptions } from "@/api/client";
import type { ChoicesResponse } from "@/api/contract.gen";
import { ApiProvider } from "@/api/provider";
import { fakeClient } from "@/test/render";

import { RelationPicker } from "./RelationPicker";

const TEAMS = [
  { value: "1", label: "Core" },
  { value: "2", label: "Docs" },
  { value: "3", label: "Infra" },
];

function Harness({ nullable = true, initial = "1" }: { nullable?: boolean; initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="team">Team</label>
      <RelationPicker
        id="team"
        label="Team"
        identity="users"
        field="team_id"
        value={value}
        initialLabel={initial === "" ? undefined : "Core"}
        nullable={nullable}
        onChange={setValue}
      />
      <output data-testid="value">{value}</output>
    </>
  );
}

function setup(props: { nullable?: boolean; initial?: string } = {}, total = 3) {
  const get = vi.fn((_url: string, options?: GetOptions) => {
    const q = String(options?.params?.q ?? "").toLowerCase();
    const items = TEAMS.filter((team) => team.label.toLowerCase().includes(q));
    return Promise.resolve<ChoicesResponse>({ items, total: q === "" ? total : items.length });
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider client={fakeClient({ get: get as unknown as ApiClient["get"] })}>
        <Harness {...props} />
      </ApiProvider>
    </QueryClientProvider>,
  );
  return { get };
}

describe("RelationPicker", () => {
  it("shows the current label and picks another option with the keyboard", async () => {
    setup();
    const box = screen.getByRole("combobox", { name: "Team" });
    expect(box).toHaveValue("Core");
    expect(box).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(box);
    expect(await screen.findByRole("option", { name: "Docs" })).toBeVisible();
    expect(box).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(screen.getByTestId("value")).toHaveTextContent("2");
    expect(box).toHaveValue("Docs");
    expect(box).toHaveAttribute("aria-expanded", "false");
  });

  it("searches on the server", async () => {
    const { get } = setup();
    const box = screen.getByRole("combobox", { name: "Team" });
    await userEvent.clear(box);
    await userEvent.type(box, "inf");
    await waitFor(() => {
      expect(get).toHaveBeenLastCalledWith(
        "/models/users/fields/team_id/choices",
        expect.objectContaining({ params: { q: "inf" } }),
      );
    });
    await userEvent.click(await screen.findByRole("option", { name: "Infra" }));
    expect(screen.getByTestId("value")).toHaveTextContent("3");
  });

  it("restores the label on Escape without changing the value", async () => {
    setup();
    const box = screen.getByRole("combobox", { name: "Team" });
    await userEvent.clear(box);
    await userEvent.type(box, "zz{Escape}");
    expect(box).toHaveValue("Core");
    expect(screen.getByTestId("value")).toHaveTextContent("1");
  });

  it("can be cleared when nullable, but not otherwise", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: "Clear Team" }));
    expect(screen.getByTestId("value")).toHaveTextContent("");
  });

  it("has no clear button for required relations", () => {
    setup({ nullable: false });
    expect(screen.queryByRole("button", { name: /Clear/ })).toBeNull();
  });

  it("says when more options exist than are shown", async () => {
    setup({}, 50);
    await userEvent.click(screen.getByRole("combobox", { name: "Team" }));
    expect(await screen.findByText("Showing 3 of 50. Type to narrow the list.")).toBeVisible();
  });

  it("supports Home, End and ArrowUp", async () => {
    setup();
    const box = screen.getByRole("combobox", { name: "Team" });
    box.focus();
    await userEvent.keyboard("{ArrowUp}");
    await screen.findByRole("option", { name: "Infra" });
    await userEvent.keyboard("{Home}{Enter}");
    expect(screen.getByTestId("value")).toHaveTextContent("1");
    await userEvent.keyboard("{ArrowDown}");
    await screen.findByRole("option", { name: "Infra" });
    await userEvent.keyboard("{End}{Enter}");
    expect(screen.getByTestId("value")).toHaveTextContent("3");
  });
});

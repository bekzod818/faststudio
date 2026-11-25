import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError, type ApiClient, type GetOptions } from "@/api/client";
import type { ListResponse, MetaResponse, Row } from "@/api/contract.gen";
import { DEV_CONFIG } from "@/lib/config";
import { testModel } from "@/test/fixtures";
import { fakeClient, renderRoutes } from "@/test/render";

import { ModelListRoute } from "./ListPage";
import { SEARCH_DELAY_MS } from "./SearchBox";

const model = testModel();
const META: MetaResponse = {
  schema_version: "1",
  version: "0.0.0",
  title: "Admin",
  show_powered_by: true,
  user: { id: "1", username: "admin" },
  capabilities: { change_password: false, sign_out_everywhere: false },
  models: [model],
};

function row(id: number, extra: Partial<Row["data"]> = {}): Row {
  return {
    pk: String(id),
    data: {
      id,
      email: `user${String(id)}@example.com`,
      is_active: true,
      status: "TODO",
      team_id: 1,
      ...extra,
    },
    labels: { team_id: "Core" },
    many_labels: {},
    truncated: [],
  };
}

function page(items: Row[], total: number, pageNumber = 1): ListResponse {
  return { items, total, page: pageNumber, page_size: model.page_size };
}

const routes = [{ path: "/models/:identity", element: <ModelListRoute /> }];

function setup(
  path: string,
  list: (options: GetOptions | undefined) => Promise<ListResponse> = () =>
    Promise.resolve(page([row(1), row(2)], 5)),
  maxListOffset = DEV_CONFIG.maxListOffset,
) {
  const get = vi.fn((url: string, options?: GetOptions) => {
    if (url === "/meta") return Promise.resolve(META);
    if (url === "/models/users/items") return list(options);
    return Promise.reject(new ApiError(404, "not_found", "Not found."));
  });
  const rendered = renderRoutes(routes, {
    client: fakeClient({ get: get as unknown as ApiClient["get"] }),
    path,
    config: { ...DEV_CONFIG, maxListOffset },
  });
  const listCalls = () =>
    get.mock.calls.filter(([url]) => url === "/models/users/items").map(([, o]) => o?.params);
  return { ...rendered, get, listCalls };
}

describe("ModelListRoute", () => {
  it("renders columns from list_display and type-aware cells", async () => {
    setup("/models/users");
    expect(await screen.findByRole("heading", { level: 1, name: "Users" })).toBeVisible();
    const table = await screen.findByRole("table", { name: "Users" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual(["ID", "Email", "Is active", "Status", "Team"]);
    expect(within(table).getByText("user1@example.com")).toBeVisible();
    expect(within(table).getAllByText("Core")).toHaveLength(2);
    expect(within(table).getAllByText("Todo")).toHaveLength(2);
    expect(screen.getByText("Showing 1–2 of 5")).toBeVisible();
  });

  it("shows the default ordering and sorts by clicking a header", async () => {
    const { router, listCalls } = setup("/models/users");
    const idHeader = await screen.findByRole("columnheader", { name: /ID/ });
    expect(idHeader).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("columnheader", { name: "Is active" })).not.toHaveAttribute(
      "aria-sort",
    );
    expect(
      within(screen.getByRole("columnheader", { name: "Is active" })).queryByRole("button"),
    ).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /Email/ }));
    await waitFor(() => {
      expect(router.state.location.search).toBe("?ordering=email");
    });
    await waitFor(() => {
      expect(listCalls().at(-1)).toEqual({ page: 1, ordering: "email" });
    });
    expect(screen.getByRole("columnheader", { name: /Email/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
  });

  it("searches after typing, resetting to page 1", async () => {
    const { router, listCalls } = setup("/models/users?page=2");
    await userEvent.type(await screen.findByRole("searchbox", { name: "Search users" }), "ann");
    await waitFor(() => {
      expect(router.state.location.search).toBe("?q=ann");
    });
    await waitFor(() => {
      expect(listCalls().at(-1)).toEqual({ page: 1, q: "ann" });
    });
  });

  it("refuses a search with control characters", async () => {
    const { router } = setup("/models/users");
    const box = await screen.findByRole("searchbox", { name: "Search users" });
    await userEvent.type(box, "a‮b{Enter}");
    expect(await screen.findByText("Search contains invalid characters.")).toBeVisible();
    expect(router.state.location.search).toBe("");
  });

  it("filters with native selects", async () => {
    const { router, listCalls } = setup("/models/users");
    await userEvent.selectOptions(await screen.findByLabelText("Status"), "Empty");
    await waitFor(() => {
      expect(router.state.location.search).toBe("?filter%5Bstatus%5D=null");
    });
    await waitFor(() => {
      expect(listCalls().at(-1)).toEqual({ page: 1, "filter[status]": "null" });
    });
    await userEvent.selectOptions(screen.getByLabelText("Is active"), "No");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "All");
    await waitFor(() => {
      expect(router.state.location.search).toBe("?filter%5Bis_active%5D=false");
    });
  });

  it("paginates", async () => {
    const { router, listCalls } = setup("/models/users", (options) =>
      Promise.resolve(page([row(9)], 5, Number(options?.params?.page))),
    );
    await screen.findByText("Page 1 of 3");
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => {
      expect(router.state.location.search).toBe("?page=2");
    });
    expect(await screen.findByText("Page 2 of 3")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Last page" }));
    expect(await screen.findByText("Page 3 of 3")).toBeVisible();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    expect(listCalls().map((params) => params?.page)).toEqual([1, 2, 3]);
  });

  it("explains an empty result and offers to clear the search", async () => {
    const { router } = setup("/models/users?q=zzz", () => Promise.resolve(page([], 0)));
    expect(await screen.findByText("No users match the current search and filters.")).toBeVisible();
    expect(screen.getByRole("searchbox", { name: "Search users" })).toHaveValue("zzz");
    await userEvent.click(screen.getByRole("button", { name: "Clear search and filters" }));
    await waitFor(() => {
      expect(router.state.location.search).toBe("");
    });
    expect(screen.getByRole("searchbox", { name: "Search users" })).toHaveValue("");
  });

  it("offers a way back when the page is past the end", async () => {
    setup("/models/users?page=9", () => Promise.resolve(page([], 5, 9)));
    expect(await screen.findByRole("button", { name: "Go to the first page" })).toBeVisible();
  });

  it("stops paging at the offset cap and says how to see more", async () => {
    // page_size 2, cap 6: pages 1-3 are reachable out of 25.
    setup(
      "/models/users?page=3",
      (options) => Promise.resolve(page([row(5)], 50, Number(options?.params?.page))),
      6,
    );
    expect(await screen.findByText("Page 3 of 3")).toBeVisible();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Last page" })).toBeDisabled();
    expect(
      screen.getByText(
        "Only the first 6 users can be paged through. Search or filter to find the rest.",
      ),
    ).toBeVisible();
  });

  it("does not mention the cap when every page is reachable", async () => {
    setup("/models/users", () => Promise.resolve(page([row(1)], 5)), 6);
    expect(await screen.findByText("Page 1 of 3")).toBeVisible();
    expect(screen.queryByText(/can be paged through/)).toBeNull();
  });

  it("explains a refused deep page (stale tab or edited link) and offers page 1", async () => {
    const { router } = setup("/models/users?page=3", (options) =>
      Number(options?.params?.page) > 1
        ? Promise.reject(
            new ApiError(400, "invalid_query", "`page` is past the last reachable page."),
          )
        : Promise.resolve(page([row(1)], 50)),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This page is too far into the list to load. Search or filter to narrow the results.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Go to the first page" }));
    await waitFor(() => {
      expect(router.state.location.search).toBe("");
    });
    expect(await screen.findByText("user1@example.com")).toBeVisible();
  });

  it("shows a load error with retry", async () => {
    let fail = true;
    setup("/models/users", () =>
      fail
        ? Promise.reject(new ApiError(500, "internal_error", "boom"))
        : Promise.resolve(page([row(1)], 1)),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load users.");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("user1@example.com")).toBeVisible();
  });

  it("ignores invalid URL parameters instead of sending them", async () => {
    const { listCalls } = setup("/models/users?page=-3&ordering=secret&filter[email]=x&q=a%00");
    await screen.findByRole("table");
    expect(listCalls()[0]).toEqual({ page: 1 });
  });

  it("shows the access page when the server refuses the list (403)", async () => {
    setup("/models/users", () => Promise.reject(new ApiError(403, "forbidden", "Forbidden.")));
    expect(await screen.findByRole("heading", { name: "Not found or no access" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("says not found or no access for a model missing from /meta", async () => {
    setup("/models/nope");
    expect(await screen.findByRole("heading", { name: "Not found or no access" })).toBeVisible();
  });

  it("keeps a search restored by the back button (no debounce wipe)", async () => {
    const { router } = setup("/models/users", (options) =>
      Promise.resolve(options?.params?.q === undefined ? page([row(1)], 1) : page([], 0)),
    );
    const box = await screen.findByRole("searchbox", { name: "Search users" });
    await userEvent.type(box, "abc");
    await waitFor(() => {
      expect(router.state.location.search).toBe("?q=abc");
    });
    await userEvent.click(await screen.findByRole("button", { name: "Clear search and filters" }));
    await waitFor(() => {
      expect(box).toHaveValue("");
    });
    await act(() => router.navigate(-1));
    await waitFor(() => {
      expect(box).toHaveValue("abc");
    });
    await new Promise((resolve) => setTimeout(resolve, SEARCH_DELAY_MS * 2));
    expect(router.state.location.search).toBe("?q=abc");
  });

  it("starting a search can be undone with back; refining it cannot flood history", async () => {
    const { router } = setup("/models/users");
    const box = await screen.findByRole("searchbox", { name: "Search users" });
    await userEvent.type(box, "ab");
    await waitFor(() => {
      expect(router.state.location.search).toBe("?q=ab");
    });
    await userEvent.type(box, "c");
    await waitFor(() => {
      expect(router.state.location.search).toBe("?q=abc");
    });
    await act(() => router.navigate(-1));
    expect(router.state.location.search).toBe("");
  });

  it("the first click on the default sort column changes the order", async () => {
    const { router } = setup("/models/users"); // default ordering: -id
    await userEvent.click(await screen.findByRole("button", { name: /ID/ }));
    await waitFor(() => {
      expect(router.state.location.search).toBe("?ordering=id");
    });
  });

  it("moves on with every click even while the next page is loading", async () => {
    const { router } = setup(
      "/models/users",
      (options) =>
        Number(options?.params?.page) === 1
          ? Promise.resolve(page([row(1), row(2)], 6))
          : new Promise<ListResponse>(() => undefined), // never resolves
    );
    const next = await screen.findByRole("button", { name: "Next page" });
    await userEvent.click(next);
    await userEvent.click(next);
    await waitFor(() => {
      expect(router.state.location.search).toBe("?page=3");
    });
    expect(screen.getByText("Page 3 of 3")).toBeVisible();
    expect(screen.getByText("Showing 1–2 of 6")).toBeVisible(); // still the rows on screen
  });

  it("keeps earlier results visible when a refresh fails", async () => {
    let fail = false;
    const { queryClient } = setup("/models/users", () =>
      fail
        ? Promise.reject(new ApiError(500, "internal_error", "boom"))
        : Promise.resolve(page([row(1)], 1)),
    );
    expect(await screen.findByText("user1@example.com")).toBeVisible();
    fail = true;
    await act(() => queryClient.refetchQueries({ queryKey: ["list"] }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not refresh users");
    expect(screen.getByText("user1@example.com")).toBeVisible();
  });
});

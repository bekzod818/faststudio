import { DEV_CONFIG, readConfig } from "./config";

function setBlock(content: string | null): void {
  document.getElementById("fs-config")?.remove();
  if (content === null) return;
  const script = document.createElement("script");
  script.type = "application/json";
  script.id = "fs-config";
  script.textContent = content;
  document.head.appendChild(script);
}

describe("readConfig", () => {
  afterEach(() => {
    setBlock(null);
  });

  it("reads the injected config block", () => {
    setBlock(
      JSON.stringify({
        schema_version: "1",
        base_url: "/back-office",
        api_url: "/back-office/api/v1",
        title: "Back Office",
        max_list_offset: 2500,
      }),
    );
    expect(readConfig()).toEqual({
      schemaVersion: "1",
      baseUrl: "/back-office",
      apiUrl: "/back-office/api/v1",
      title: "Back Office",
      maxListOffset: 2500,
    });
  });

  it("ignores unknown keys, like the server may add later", () => {
    setBlock(JSON.stringify({ ...valid, max_list_offset: 7, future_field: true }));
    expect(readConfig()).toEqual({
      schemaVersion: "1",
      baseUrl: "/a",
      apiUrl: "/a/api/v1",
      title: "t",
      maxListOffset: 7,
    });
  });

  it("falls back to the development config when the block is missing", () => {
    expect(readConfig()).toEqual(DEV_CONFIG);
  });

  const valid = { schema_version: "1", base_url: "/a", api_url: "/a/api/v1", title: "t" };

  it.each([
    JSON.stringify(valid), // no max_list_offset
    JSON.stringify({ ...valid, max_list_offset: 0 }),
    JSON.stringify({ ...valid, max_list_offset: 1.5 }),
    JSON.stringify({ ...valid, max_list_offset: "10000" }),
    "not json",
    JSON.stringify({ schema_version: "2", base_url: "/a", api_url: "/a/api/v1", title: "t" }),
    JSON.stringify({ schema_version: "1", base_url: "//evil", api_url: "/a", title: "t" }),
    JSON.stringify({ schema_version: "1", base_url: "/a", api_url: "https://evil/x", title: "t" }),
    JSON.stringify({ ...valid, max_list_offset: 10, title: "" }),
    JSON.stringify({ ...valid, max_list_offset: 10, base_url: "/a b" }),
    JSON.stringify({ ...valid, max_list_offset: 10, base_url: "/a\\b" }),
    JSON.stringify({ ...valid, max_list_offset: 10, api_url: "/x://y" }),
    JSON.stringify({ ...valid, max_list_offset: 10, api_url: "relative" }),
    JSON.stringify({ ...valid, max_list_offset: 10, title: 5 }),
    JSON.stringify({ ...valid, max_list_offset: -1 }),
    JSON.stringify({ ...valid, max_list_offset: Number.POSITIVE_INFINITY }),
    JSON.stringify({ ...valid, max_list_offset: 1e21 }), // beyond the safe integers, as zod
    JSON.stringify({ ...valid, max_list_offset: 2 ** 53 }),
    JSON.stringify([valid]),
    "null",
    '"a string"',
  ])("rejects an invalid block: %s", (content) => {
    setBlock(content);
    expect(() => readConfig()).toThrow(/FastStudio/);
  });
});

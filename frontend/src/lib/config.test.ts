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
      }),
    );
    expect(readConfig()).toEqual({
      schemaVersion: "1",
      baseUrl: "/back-office",
      apiUrl: "/back-office/api/v1",
      title: "Back Office",
    });
  });

  it("falls back to the development config when the block is missing", () => {
    expect(readConfig()).toEqual(DEV_CONFIG);
  });

  it.each([
    "not json",
    JSON.stringify({ schema_version: "2", base_url: "/a", api_url: "/a/api/v1", title: "t" }),
    JSON.stringify({ schema_version: "1", base_url: "//evil", api_url: "/a", title: "t" }),
    JSON.stringify({ schema_version: "1", base_url: "/a", api_url: "https://evil/x", title: "t" }),
  ])("rejects an invalid block: %s", (content) => {
    setBlock(content);
    expect(() => readConfig()).toThrow(/FastStudio/);
  });
});

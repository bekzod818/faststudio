import { safeNext } from "./navigation";

describe("safeNext", () => {
  it.each([
    ["/models/users", "/models/users"],
    ["/models/users?page=2#top", "/models/users?page=2#top"],
    ["/", "/"],
  ])("keeps in-app path %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });

  it.each([
    null,
    "",
    "//evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "https://evil.example",
    "javascript:alert(1)",
    "models/users",
    "/login",
    "/login?next=/x",
    " /models",
    "/%0d%0aSet-Cookie:x",
    "/login/",
    "/LOGIN",
    "/Login?x=1",
    "/login//#a",
    "/%E2%80%AEevil",
    "/%C2%85x",
    "/%5Cevil.example",
    "/%E0bad",
    "/%6Cogin",
    "/%4C%4F%47%49%4E/",
  ])("rejects %s", (input) => {
    expect(safeNext(input)).toBe("/");
  });
});

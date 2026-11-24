import { readCookie } from "./cookies";

describe("readCookie", () => {
  it("reads and decodes a cookie", () => {
    expect(readCookie("b", "a=1; b=x%20y; c=3")).toBe("x y");
  });

  it("keeps '=' inside values", () => {
    expect(readCookie("t", "t=abc==")).toBe("abc==");
  });

  it("returns undefined when absent", () => {
    expect(readCookie("missing", "a=1")).toBeUndefined();
  });

  it("treats a malformed value as absent instead of throwing", () => {
    expect(readCookie("faststudio_csrftoken", "faststudio_csrftoken=%E0")).toBeUndefined();
  });
});

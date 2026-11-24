import { Database, Users } from "lucide-react";

import { modelIcon } from "./icons";

describe("modelIcon", () => {
  it("resolves known names", () => {
    expect(modelIcon("users")).toBe(Users);
  });

  it.each([null, undefined, "", "unknown", "constructor", "toString", "__proto__"])(
    "falls back to Database for %s",
    (name) => {
      expect(modelIcon(name)).toBe(Database);
    },
  );
});

import { z } from "zod";

import "./zod-setup";

it("disables zod's eval-based JIT (strict CSP)", () => {
  expect(z.config().jitless).toBe(true);
});

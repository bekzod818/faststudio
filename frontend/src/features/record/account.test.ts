import type { Row } from "@/api/contract.gen";
import { testModel } from "@/test/fixtures";

import { isOwnAccount, withProtectedFields } from "./account";

const row: Row = { pk: "1", data: {}, labels: {} };
const accounts = testModel({ account: { protected_fields: ["is_active"] } });

describe("isOwnAccount", () => {
  it("matches the signed-in admin's record of the accounts model", () => {
    expect(isOwnAccount(accounts, row, "1")).toBe(true);
    expect(isOwnAccount(accounts, row, "2")).toBe(false);
    expect(isOwnAccount(accounts, row, undefined)).toBe(false);
    expect(isOwnAccount(testModel(), row, "1")).toBe(false);
  });
});

describe("withProtectedFields", () => {
  it("marks only the protected fields read-only", () => {
    const fields = withProtectedFields(accounts).fields;
    expect(fields.find((f) => f.name === "is_active")?.readonly).toBe(true);
    expect(fields.find((f) => f.name === "email")?.readonly).toBe(false);
    expect(accounts.fields.find((f) => f.name === "is_active")?.readonly).toBe(false); // not mutated
  });
});

import { hasForbiddenCharacters } from "./text";

describe("hasForbiddenCharacters", () => {
  it.each(["admin", "o'brien@example.com", "Bekzod Ali", "\u0411\u0435\u043a"])(
    "accepts %s",
    (value) => {
      expect(hasForbiddenCharacters(value)).toBe(false);
    },
  );

  it.each([0x00, 0x0a, 0x1f, 0x7f, 0x85, 0x9f, 0x2028, 0x2029, 0x202e, 0x2066])(
    "rejects U+%s",
    (code) => {
      expect(hasForbiddenCharacters(`a${String.fromCodePoint(code)}b`)).toBe(true);
    },
  );
});

// Generate src/api/contract.gen.ts from the backend's JSON Schema (ADR-0007).
//
//   pnpm gen:contract          write the file
//   pnpm gen:contract --check  exit 1 if the committed file is stale
//
// Source of truth: src/faststudio/schemas/contract.py (Pydantic). Regenerate the
// JSON Schema first with `uv run python scripts/export_contract.py`.
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { compile } from "json-schema-to-typescript";

const SCHEMA = fileURLToPath(
  new URL("../../src/faststudio/schemas/contract.schema.json", import.meta.url),
);
const OUTPUT = fileURLToPath(new URL("../src/api/contract.gen.ts", import.meta.url));

const BANNER = `/* eslint-disable */
/**
 * GENERATED FILE - DO NOT EDIT.
 * Source: src/faststudio/schemas/contract.py -> contract.schema.json
 * Regenerate: uv run python scripts/export_contract.py && pnpm -C frontend gen:contract
 */`;

const args = process.argv.slice(2);
if (args.some((arg) => arg !== "--check")) {
  console.error("usage: gen-contract.mjs [--check]");
  process.exit(2);
}

const schema = JSON.parse(await readFile(SCHEMA, "utf8"));
const output = await compile(schema, "FastStudioContract", {
  bannerComment: BANNER,
  additionalProperties: false,
  unreachableDefinitions: true,
  strictIndexSignatures: true,
  style: { printWidth: 100, semi: true, singleQuote: false, trailingComma: "all" },
});

if (args.includes("--check")) {
  let current = "";
  try {
    current = await readFile(OUTPUT, "utf8");
  } catch {
    // missing file counts as stale
  }
  if (current !== output) {
    console.error(`ERROR: ${OUTPUT} is out of date; run \`pnpm -C frontend gen:contract\`.`);
    process.exit(1);
  }
  console.log("OK: contract.gen.ts is up to date");
} else {
  await writeFile(OUTPUT, output);
  console.log(`wrote ${OUTPUT}`);
}

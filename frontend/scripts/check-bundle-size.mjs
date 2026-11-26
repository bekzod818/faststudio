// Fail when the entry chunk reaches Vite's 500 kB warning size (v0.2 item 5).
// Rarely used routes load lazily (App.tsx); this keeps it that way in CI,
// where Vite's warning would go unnoticed. Run after `pnpm build`.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const LIMIT = 500_000; // bytes: Vite's chunkSizeWarningLimit (500 kB, 1 kB = 1000 B)
const here = dirname(fileURLToPath(import.meta.url));
const staticDir = join(here, "..", "..", "src", "faststudio", "static");
const html = readFileSync(join(staticDir, "index.html"), "utf8");
const entry = /<script type="module"[^>]*src="[^"]*?(assets\/[^"]+\.js)"/u.exec(html)?.[1];
if (entry === undefined) {
  console.error("check-bundle-size: no entry script in index.html (run pnpm build first)");
  process.exit(1);
}
// Read once: both sizes come from the same bytes (no stat-then-read race).
const bytes = readFileSync(join(staticDir, entry));
const raw = bytes.length;
const gzip = gzipSync(bytes).length;
const kb = (n) => `${(n / 1000).toFixed(2)} kB`;
console.log(`entry ${entry}: ${kb(raw)} (gzip, node default: ${kb(gzip)}), limit ${kb(LIMIT)}`);
if (raw >= LIMIT) {
  console.error("check-bundle-size: the entry chunk is too large; lazy-load more routes");
  process.exit(1);
}

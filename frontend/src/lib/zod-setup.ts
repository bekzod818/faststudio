import { z } from "zod";

// zod probes `new Function("")` to decide whether to JIT-compile object
// parsers. The admin CSP forbids eval, and browsers report the blocked probe
// as a CSP violation even though zod catches it. Must run before any parse:
// every module that imports zod imports this first (zod lives in lazy chunks,
// out of the boot path; src/lib/zod-imports.test.ts checks both).
z.config({ jitless: true });

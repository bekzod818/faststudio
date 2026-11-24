import { z } from "zod";

// zod probes `new Function("")` to decide whether to JIT-compile object
// parsers. The admin CSP forbids eval, and browsers report the blocked probe
// as a CSP violation even though zod catches it. Must run before any parse:
// imported first by main.tsx.
z.config({ jitless: true });

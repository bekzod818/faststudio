# ADR-0005: Runtime base_url injection

- Status: Accepted
- Date: 2026-11-23

## Context

Users choose the mount path (`base_url`) at runtime, but the SPA is built once
at release time.

## Decision

- Vite builds with `base: "./"` so all asset URLs are relative.
- On each SPA request the server renders `index.html`, inserting
  `<base href="{base_url}/">` and a JSON config block
  `<script type="application/json" id="fs-config">{...}</script>` at the
  `<!-- faststudio:head -->` marker. JSON is HTML-escaped (`<`, `>`, `&`).
- React Router uses `basename = config.base_url`; the API client uses
  `config.api_url`.
- History fallback: any non-asset, non-API path under `base_url` returns the
  rendered index; `/api/*` never falls back (JSON 404).

## Consequences

- One build works under any path, including behind path-prefix proxies.
- No inline executable script, so a strict CSP (`script-src 'self'`) works.
- index.html is rendered per request (cheap: cached template, string insert).

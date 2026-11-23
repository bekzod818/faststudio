# ADR-0006: Mount the admin as an isolated sub-application

- Status: Accepted
- Date: 2026-11-23
- Refined by: ADR-0008 (host middleware, error propagation, proxy prefixes)

## Context

FastStudio must not alter the host application's behaviour, OpenAPI schema,
middleware or exception handling.

## Decision

`Admin` builds its own `FastAPI` instance (OpenAPI/docs disabled) and mounts it
with `app.mount(base_url, sub_app)`. Security headers, CSRF, error handlers and
the JSON error format live only on the sub-app.

## Consequences

- Host app's `/docs` stays clean; host middleware still runs around the mount
  (e.g. host CORS or GZip), which is expected.
- Admin headers/CSP never leak onto host routes.
- Host-level dependency overrides do not apply inside the admin; FastStudio
  exposes its own configuration instead.

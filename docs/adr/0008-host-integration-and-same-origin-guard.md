# ADR-0008: Host integration boundaries and the same-origin API guard

- Status: Accepted
- Date: 2026-11-23
- Refines: ADR-0006 (isolated sub-application)

## Context

ADR-0006 mounts the admin as an isolated sub-application, but a mount cannot
be fully isolated from the host:

1. **Host middleware wraps the mount.** A host `CORSMiddleware` configured
   permissively (`allow_origin_regex=".*", allow_credentials=True`) adds
   `Access-Control-Allow-Origin`/`-Credentials` to admin responses, so any
   website could read admin JSON with the admin's cookies. CSRF tokens only
   protect unsafe methods.
2. **Unhandled errors propagate.** Starlette's error middleware sends the
   admin's generic 500 and then re-raises, so host exception handlers and the
   server's error logging see admin failures.
3. **Path-prefix proxies.** Behind `uvicorn --root-path /prefix`, the
   browser-visible mount root is `/prefix{base_url}`.

## Decision

1. Every `/api/*` request, **including GET**, passes a same-origin guard
   (`security/origin.py`): requests whose `Sec-Fetch-Site` is not
   `same-origin`/`none`, or (without that header) whose `Origin` differs from
   the request's own scheme and host, get `403 csrf_failed`. Requests with
   neither header (non-browser clients) pass; authentication still applies.
2. Admin 500s keep propagating to the host after the generic response is
   sent. This is intentional: host monitoring (Sentry, logs) must see admin
   failures. FastStudio logs them once on `faststudio.api`; the host may log
   them again.
3. The SPA shell, `<base href>` and `SpaConfig` are rendered per mount root
   (proxy prefix + `base_url`, cached per root), and the trailing-slash
   redirect uses the ASGI `path`, which already contains `root_path`.

## Consequences

- A permissive host CORS policy cannot expose admin data; the host's own
  preflight responses still reach browsers but the real request is refused.
- Server-to-server API clients are not blocked by the guard.
- Hosts see each admin 500 in their own error handling.
- A client that disconnects while sending a body (`ClientDisconnect`) is
  not an error: it is logged at debug level and not re-raised to the host
  (v0.2 item 5). Nothing is written, since the body never arrived; proxy
  logs still show such requests.

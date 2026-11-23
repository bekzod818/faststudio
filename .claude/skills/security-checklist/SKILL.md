---
name: security-checklist
description: The security checklist every FastStudio change must pass before commit. Use when finishing any milestone or any change touching auth, sessions, CSRF, API routes, query building, writes, SPA serving, headers, dependencies or secrets.
---

# Security checklist

Mark each item ✅ / N/A with evidence (test name or command output). Any ❌
blocks the commit. Never weaken a check to make a test pass.

## Authentication & sessions
- [ ] New routes depend on the session dependency (only `POST /auth/login` is exempt); the route-enumeration test still passes.
- [ ] Session cookie flags unchanged: HttpOnly, Secure, SameSite=Lax, Path=base_url.
- [ ] Auth failures return the generic `invalid_credentials` / `not_authenticated` errors; no enumeration via message, status, or timing.

## CSRF
- [ ] Every new unsafe-method route goes through CSRF validation.
- [ ] Token comparisons use `hmac.compare_digest`.

## Injection
- [ ] No `text()`, f-string, `%` or `.format()` SQL with request data.
- [ ] Any new query parameter that names a field is validated against a ModelAdmin allowlist; unknown → 400 `invalid_query`.
- [ ] LIKE patterns escape `%`, `_` and the escape character.
- [ ] Page size capped by `max_page_size`.

## Mass assignment & exposure
- [ ] Write models use `extra="forbid"` and contain only writable fields.
- [ ] `exclude`d fields absent from every response (meta, list, retrieve, choices, errors).
- [ ] `can_create` / `can_edit` / `can_delete` enforced server-side.
- [ ] Error responses never include SQL, stack traces, or secrets.

## XSS & headers
- [ ] No `dangerouslySetInnerHTML` / `innerHTML` (ESLint passes).
- [ ] JSON config injection still escapes `<`, `>`, `&`.
- [ ] CSP and security headers present on new response types; no inline scripts added.

## Secrets & dependencies
- [ ] No secrets, tokens, or real credentials in code, tests, fixtures or docs (gitleaks passes).
- [ ] Logging never includes passwords, hashes, cookies or tokens.
- [ ] New dependencies justified; `uv run pip-audit` and `pnpm -C frontend audit` clean.

## Tests & docs
- [ ] Each control touched has tests for allowed **and** rejected paths.
- [ ] `docs/threat-model.md` updated if a control was added or changed.
- [ ] `uv run bandit -c pyproject.toml -r src` clean.

Finish by asking the `security-reviewer` subagent for SIGN-OFF.

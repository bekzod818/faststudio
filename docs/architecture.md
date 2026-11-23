# Architecture

> Status: v0.1.0 in development. Sections describe the target MVP design
> approved in Phase 1; implementation status is tracked in the milestone table.

## Overview

```
Browser ──► {base_url}/            SPA shell (index.html + config JSON)  ┐
        ──► {base_url}/assets/*    hashed static assets (immutable)      │ isolated FastAPI
        ──► {base_url}/api/v1/*    JSON API (auth, meta, CRUD)           │ sub-application
                                                                         ┘ (ADR-0006)
            Host FastAPI app  ── unchanged; FastStudio only adds one mount
```

FastStudio is two halves joined by a versioned JSON contract:

1. **Python package** (`src/faststudio`): introspects SQLAlchemy mappers,
   validates `ModelAdmin` declarations at startup, serves the API and the SPA.
2. **React SPA** (`frontend/`, built into `src/faststudio/static`): a generic
   UI that renders any model from metadata (ADR-0003). It has no per-model code.

## Request lifecycle

1. `Admin(app, ...)` validates configuration (secret strength, base_url) and
   mounts a sub-application at `base_url`.
2. `admin.register(SomeAdmin)` validates every option against the mapper,
   introspects fields (`introspection/`) and generates Pydantic input models
   (`schemas/_dynamic.py`). Misconfiguration raises `ConfigurationError` at
   import time, never at request time.
3. Requests pass the security-headers middleware, then the CSRF check (unsafe
   methods), then the session dependency (all routes except login).
4. List queries are built only in `query/` from allowlisted field names
   mapped to SQLAlchemy column objects. User input never becomes SQL text.

## Package layout

| Module | Responsibility |
|---|---|
| `admin.py` | `Admin`: configuration, mounting, registration entry point |
| `config.py` | validated `Settings`, `base_url` normalization (private) |
| `exceptions.py` | `FastStudioError` hierarchy (`ConfigurationError`, ...) |
| `model_admin.py` | `ModelAdmin` declarative options |
| `registry.py` | validates `ModelAdmin` classes into frozen `RegisteredModel`s; identity → model (private) |
| `introspection/` | SQLAlchemy column → `FieldSpec` (`_types.py` type mapping, `_fields.py` flags; see `api-contract.md`) |
| `schemas/` | Pydantic API contract (exported to JSON Schema / TypeScript) |
| `query/` | safe search/filter/sort/paginate builders |
| `api/` | sub-app factory, routers (`auth`, `meta`, `crud`), error handling |
| `auth/` | `AuthBackend` protocol, `ModelUserBackend`, passwords, session, CSRF |
| `security/` | headers/CSP, rate limiting, secret validation |
| `_spa.py` | index.html rendering, runtime config injection, history fallback |

## Extension points (designed now, public later)

- `AuthBackend` and `RateLimiter` are public protocols in v0.1.0.
- Field types resolve through an internal registry (`introspection/_types.py`);
  a public registry for custom types/widgets is planned (ROADMAP v0.2).
- `ModelAdmin` query hooks (`_get_list_query`) stay private until an ADR
  promotes them.
- The metadata payload carries `schema_version` so the SPA and backend can
  evolve independently; additive changes keep version `"1"`.

## Milestones

| # | Milestone | Status |
|---|---|---|
| M0 | Scaffold, tooling, CI | done |
| M1 | Config, exceptions, `Admin` init, secret validation | done |
| M2 | `ModelAdmin` + registry validation | done |
| M3 | Introspection | done |
| M4 | Contract schemas + TypeScript codegen | planned |
| M5 | Sub-app mount, SPA serving, security headers | planned |
| M6 | Auth, CSRF, rate limiting, `ModelUserBackend` | planned |
| M7 | Meta + read API | planned |
| M8 | Write API | planned |
| M9 | Frontend foundation (layout, login, dashboard) | planned |
| M10 | List view | planned |
| M11 | Forms, delete, toasts | planned |
| M12 | Example app, Playwright E2E, wheel smoke | planned |
| M13 | Docs, security sign-off, v0.1.0 release | planned |

Each milestone: tests first → implementation → ruff/mypy/pytest → security
and code review → docs/CHANGELOG → commit.

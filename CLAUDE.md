# CLAUDE.md — FastStudio

## Project identity

- Brand / display name: **FastStudio**
- PyPI distribution: `faststudio` (`pip install faststudio`)
- Python import package: `faststudio` (`from faststudio import Admin`)
- npm package (frontend, private, not published): `@faststudio/ui`
- GitHub: github.com/bekzod818/faststudio
- Author / maintainer: Bekzod (bekzod818)
- License: MIT, copyright "2026 Bekzod"
- Tagline: "A modern, beautiful admin studio for FastAPI."
- Short description: "Plug-and-play admin panel for FastAPI and SQLAlchemy 2.0 with a modern React UI."
- Status: Alpha (v0.x); public API may change until v1.0
- Default mount path `/admin` (`base_url`); default UI title "FastStudio"

## Purpose

Installable library that adds a Django-Admin-style panel to any FastAPI app on
SQLAlchemy 2.0 async. Declarative `ModelAdmin` classes; a generic,
schema-driven React SPA pre-built into the wheel (users never need Node).
Secure by default, typed end to end, fully tested.

## Architecture (see docs/architecture.md, docs/adr/)

- `Admin` mounts an **isolated FastAPI sub-app** at `base_url` (ADR-0006):
  SPA at `{base_url}/`, JSON API at `{base_url}/api/v1`.
- `register()` validates `ModelAdmin` options against the mapper and fails
  loudly at startup (`ConfigurationError`).
- `introspection/` maps SQLAlchemy columns → `FieldMeta`; `schemas/` holds the
  Pydantic contract (exported to JSON Schema → TS, ADR-0007); `query/` is the
  **only** place list SQL is built; `auth/` + `security/` own sessions, CSRF,
  rate limiting, headers.
- SPA reads runtime config from a JSON block injected into index.html
  (ADR-0005) and renders everything from `/api/v1/meta` (ADR-0003).
- Auth: core owns signed stateless session cookie + CSRF; `AuthBackend` only
  authenticates/loads users; `ModelUserBackend` uses the host's user model (ADR-0004).

## Commands

```bash
uv sync                                    # install Python env + dev tools
pnpm -C frontend install                   # install frontend deps
uv run pytest --cov                        # tests + coverage (fail_under 90)
uv run ruff check . && uv run ruff format --check .   # lint/format
uv run mypy                                # mypy --strict (src, tests, scripts)
uv run bandit -c pyproject.toml -r src     # security lint
pnpm -C frontend lint | typecheck | test | build      # frontend checks / build SPA
pnpm -C frontend test:e2e                  # Playwright
uv build && uv run python scripts/verify_wheel.py dist/*.whl   # wheel with SPA
uv run python scripts/export_contract.py && pnpm -C frontend gen:contract  # contract sync (M4+)
uv run python -m examples.basic                   # example app (see examples/basic/README.md)
uv run pre-commit run --all-files          # all hooks
```

## Conventions

- Python ≥ 3.11, src layout, full annotations, `mypy --strict`, ruff (line 100).
- Public API = names exported in `faststudio/__init__.py`. Everything else is
  private (`_` prefix for modules/functions not meant for users).
- SQLAlchemy 2.0 async style only; Pydantic v2 only.
- Tests first. Unit in `tests/unit`, HTTP in `tests/integration` (httpx
  `AsyncClient` + aiosqlite), security in `tests/integration/security`.
- Conventional Commits; small reviewable commits; Keep a Changelog
  ("Unreleased"); SemVer.
- All code, comments, docs and commit messages in English.

### Naming

| Thing | Convention |
|---|---|
| Env vars | `FASTSTUDIO_` prefix (`FASTSTUDIO_SECRET_KEY`) |
| Session cookie | `faststudio_session` |
| CSRF cookie / header | `faststudio_csrftoken` / `X-FastStudio-CSRF` |
| Logger | `faststudio` (children: `faststudio.api`, `faststudio.auth`, ...) |
| Exceptions | subclass `FastStudioError` (`faststudio.exceptions`) |
| Browser storage keys | `faststudio:` prefix (`faststudio:theme`) |
| CSS custom properties | `--fs-` prefix |
| API base | `{base_url}/api/v1` |
| Metadata schema version | `"1"` |

## Security rules (non-negotiable; see docs/threat-model.md)

- Every API route except login requires an authenticated session.
- CSRF validation on POST/PUT/PATCH/DELETE (login included).
- Never build SQL with string formatting; search/filter/sort fields only from
  ModelAdmin allowlists; cap page_size.
- Rate-limit login; constant-time secret comparisons; generic auth errors.
- Security headers + strict CSP on all admin responses; no inline scripts.
- No secrets in the repo; weak/missing `FASTSTUDIO_SECRET_KEY` fails startup.
- Writes honour `readonly_fields` / `exclude` (`extra="forbid"`).
- Every protection has tests for allowed and rejected paths.

## Workflow per milestone

tests first → implement → ruff, mypy, pytest (+ frontend checks) →
`security-reviewer` and `code-reviewer` subagents → fix → docs + CHANGELOG →
commit → short summary + next step. Use skills in `.claude/skills/`
(`security-checklist`, `api-contract-sync`, `add-field-type`,
`add-modeladmin-option`, `release`).

## Definition of done (per change)

- [ ] Tests written first and passing; coverage ≥ 90 % (100 % for auth/security/query).
- [ ] ruff, ruff format, mypy --strict, bandit clean; frontend lint/typecheck/test/build clean if touched.
- [ ] Security checklist passed; security-reviewer SIGN-OFF for security-relevant changes.
- [ ] code-reviewer APPROVE.
- [ ] Docs and CHANGELOG updated; ADR if architecture/public API changed.
- [ ] Check results shown before claiming done.

## Never do

- Never commit built static files (`src/faststudio/static/`).
- Never disable, skip, xfail or loosen tests to get green.
- Never weaken a security check to make tests pass.
- Never rename or remove public API without an ADR.
- Never copy code, templates, styles or assets from django-unfold or other admin projects.
- Never publish to PyPI, push tags, or change GitHub settings without the maintainer's explicit confirmation.
- Never hand-edit generated contract files.
- Never change a locked tech decision (see docs/architecture.md and ADRs) without asking.

# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While in `0.x`, minor releases may contain breaking changes; they are always
listed under **Changed** or **Removed** with migration notes.

## [Unreleased]

### Added

- Project scaffold: packaging with a wheel build hook that bundles the React SPA,
  CI (lint, mypy, tests on Python 3.11–3.13, security scans, wheel smoke test,
  Playwright E2E), release workflow with PyPI Trusted Publishing, CodeQL and
  Dependabot.
- Architecture docs, threat model and ADRs 0001–0007.
- `Admin` validates all options (values and types) at startup and raises
  `ConfigurationError` on misconfiguration: exactly one of `engine` (must be an
  `AsyncEngine`) or `session_maker`, an `AuthBackend` instance with async
  methods, title, `base_url`, `session_max_age` and `max_page_size` bounds.
- Secret key resolution from `secret_key=` or `FASTSTUDIO_SECRET_KEY`; startup
  fails if it is missing, too short, a known placeholder, sequential or a
  keyboard run, low diversity, hand-written and under 43 characters, or has
  surrounding whitespace. The secret never appears in error messages or `repr`.
- Public `AuthBackend` protocol and `AuthenticatedUser` dataclass with a
  required, non-empty `auth_version` for session revocation.
- `ModelAdmin` declarative options and `Admin.register()` (also usable as a
  class decorator). Registration validates everything at startup: mapped
  model, single-column primary key, unique identity and model, field names
  (with the list of available fields in the error), text-only
  `search_fields`, boolean/enum-only `list_filter`, `ordering` syntax,
  `page_size` within `max_page_size`, and that `exclude`d fields are not
  displayed, searched, filtered, sorted, made readonly or labelled (including
  through another attribute mapped to the same column). Unknown public class
  attributes are rejected so a misspelled option never fails open; typos and
  Django/SQLAdmin option names get a suggestion. Joined-table inheritance is
  supported. Visible fields with sensitive-looking names log a warning.
- Introspection of every visible column into a field description: type
  (`string`, `text`, `integer`, `float`, `decimal`, `boolean`, `date`,
  `datetime`, `enum`, `json`, `uuid`, `foreign_key`, `unsupported`),
  label, nullable/required/readonly flags, JSON-safe default, max length,
  enum choices, many-to-one relation target, timezone, precision/scale and
  help text from the column comment, integer ranges, and a `create_only` flag
  for natural primary keys. Writability fails closed: database- or
  SQLAlchemy-maintained columns, value-converting `TypeDecorator`s and
  unsupported types are read-only; relations only target primary keys;
  sensitive and unsupported defaults are not published. A warning is logged
  when `can_create` is enabled but a required column can never be supplied.
- Versioned API contract (`schema_version` "1") as frozen Pydantic models
  (`MetaResponse`, `ModelMeta`, `FieldMeta`, `ListResponse`, `Row`,
  `ChoicesResponse`, `UserResponse`, `LoginRequest`, `ErrorResponse`), with
  `ModelMeta` built from registered models (relation targets resolved
  across the registry, preferring the table owner under single-table
  inheritance; sortable-field allowlist computed at registration). Login
  passwords never appear in `repr` or errors, usernames reject control
  characters, error details never echo inputs, and unsafe integer bounds
  are not published.
- `scripts/export_contract.py` exports the contract to a committed,
  deterministic JSON Schema; `pnpm gen:contract` generates
  `frontend/src/api/contract.gen.ts` from it. CI and pre-commit fail on drift.

## [0.0.1] - 2026-11-23

### Added

- Name reservation placeholder release on PyPI.

[Unreleased]: https://github.com/bekzod818/faststudio/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/bekzod818/faststudio/releases/tag/v0.0.1

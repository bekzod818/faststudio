# Roadmap

FastStudio follows small, focused releases. Dates are not promised; order may
change based on feedback. Items marked *(ADR)* need an architecture decision
record before work starts.

## v0.1.0 — MVP (released)

Admin mounting, `ModelAdmin` options, SQLAlchemy introspection, versioned
metadata contract, CRUD API with search/filter/sort/pagination, built-in
session authentication with CSRF, React SPA (login, dashboard, list, forms,
dark mode), `examples/basic`. See the milestones in `docs/architecture.md`.

## v0.1.1 — Hardening (released)

Admin self-lockout and last-admin protection (ADR-0009), lock races answered
with 409, a configurable list offset cap (`max_list_offset`), a test-suite
leak guard, and a clearer threat model for sessions.

## v0.2 — Relationships, users and permissions

- Many-to-many fields (simple association tables) with a searchable
  multi-select *(ADR)*
- `faststudio.contrib.auth`: Django-style users, groups and permissions next
  to `ModelUserBackend`; permission checks on every route and per-model
  `has_*_permission` hooks *(ADR)*
- `faststudio` CLI: `createadmin`, `changepassword`, `syncpermissions` *(ADR)*
- Session improvements: optional idle timeout and "sign out everywhere"
  (still stateless) *(ADR)*

## v0.3 — Actions, extensibility and auditing

- Custom bulk and row actions *(ADR)*
- Public extension points: custom field types and form widgets registry *(ADR)*
- Audit log of admin changes
- Server-side session store (revocable sessions; Redis/DB backends)
- Shared rate limiter backends (Redis), including the per-client login budget
- Composite primary keys
- Association objects with extra columns and inline/related editing

## v0.4 — Data workflows

- File and image uploads with pluggable storage *(ADR)*
- Export to CSV / Excel
- Dashboard widgets and charts

## v0.5 — Ecosystem

- i18n: English, Uzbek, Russian
- Theming API (colors, logo, fonts)
- Synchronous SQLAlchemy sessions
- SQLModel-specific conveniences; evaluate Tortoise ORM / Beanie support *(ADR)*
- Documentation website

## v1.0

Stable public API, deprecation policy, long-term support for the latest minor.

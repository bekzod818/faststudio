# Roadmap

FastStudio follows small, focused releases. Dates are not promised; order may
change based on feedback. Items marked *(ADR)* need an architecture decision
record before work starts.

## v0.1.0 — MVP (released)

Admin mounting, `ModelAdmin` options, SQLAlchemy introspection, versioned
metadata contract, CRUD API with search/filter/sort/pagination, built-in
session authentication with CSRF, React SPA (login, dashboard, list, forms,
dark mode), `examples/basic`. See the milestones in `docs/architecture.md`.

## v0.1.x

- Configurable per-client login budget (shared backend for multi-worker
  deployments) *(ADR)*

## v0.2 — Relationships and actions

- Many-to-many fields and inline/related editing *(ADR)*
- Custom bulk and row actions *(ADR)*
- Composite primary keys
- Public extension points: custom field types and form widgets registry *(ADR)*

## v0.3 — Access control and auditing

- Granular role-based permissions per model and action *(ADR)*
- Audit log of admin changes
- Server-side session store (revocable sessions; Redis/DB backends)
- Shared rate limiter backends (Redis)

## v0.4 — Data workflows

- File and image uploads with pluggable storage *(ADR)*
- Export to CSV / Excel
- Dashboard widgets and charts

## v0.5 — Ecosystem

- i18n: English, Uzbek, Russian
- Theming API (colors, logo, fonts)
- Synchronous SQLAlchemy sessions
- SQLModel-specific conveniences; evaluate Tortoise ORM / Beanie support *(ADR)*
- `faststudio` CLI (e.g. `faststudio create-admin-user`)
- Documentation website

## v1.0

Stable public API, deprecation policy, long-term support for the latest minor.

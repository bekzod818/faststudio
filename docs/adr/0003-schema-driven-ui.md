# ADR-0003: Schema-driven generic UI

- Status: Accepted
- Date: 2026-11-23

## Context

Django-style admins generate UI per model. With a prebuilt SPA we cannot
generate frontend code per user model.

## Decision

The backend publishes a versioned metadata document (`GET /api/v1/meta`,
`schema_version: "1"`) describing every registered model and field. The SPA is
generic: list columns, filters, form widgets and validation (Zod schemas) are
derived from that metadata at runtime. The server remains the source of truth
and re-validates every input.

## Consequences

- No per-model frontend code; adding a model is purely Python.
- New field types need coordinated backend + frontend work (see the
  `add-field-type` skill); custom widgets require a future registry (ROADMAP).
- Additive metadata changes keep `schema_version`; breaking ones bump it.

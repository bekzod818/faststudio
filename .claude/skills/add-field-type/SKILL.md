---
name: add-field-type
description: Step-by-step procedure for supporting a new SQLAlchemy column type end to end in FastStudio - introspection, contract schema, input validation, form widget, table cell, and tests. Use whenever a column type currently maps to "unsupported" or a new FieldType is requested.
---

# Add a field type

A field type spans backend and frontend. Do every step; skipping one produces
a type that renders but cannot be edited safely (or vice versa).

## 0. Decide
- Name the `FieldType` value (snake_case, e.g. `ip_address`). Adding a value is
  additive: `schema_version` stays `"1"`. Changing an existing mapping is
  breaking: write an ADR and bump `schema_version`.
- Define the **wire format** (JSON representation) and the **input validator**.
  Prefer strings for anything that loses precision as a JS number.
- Update the mapping table in `docs/api-contract.md` first.

## 1. Tests first (backend)
- Add a column of the new type to `AllTypes` in `tests/factories/models.py`
  and the matching row to `TYPE_TABLE` in
  `tests/unit/introspection/test_fields.py` (same order:
  `test_every_column_is_classified` checks it).
- Add cases asserting `type`, `nullable`, `required`, `readonly`,
  `create_only`, `default` (wire format) and any type-specific flag.
- `tests/integration/`: create + retrieve round trip; invalid value → 422 with
  `validation_error` details; value appears correctly in list response.

## 2. Introspection
- `src/faststudio/introspection/_types.py`: add the literal to `FieldType` and
  the SQLAlchemy class to `_SIMPLE_TYPES`, **more specific classes before their
  bases**. If SQLAlchemy emulates it with a `TypeDecorator`, add it to
  `_EMULATED` instead. `base_type()` in `_columns.py` already fails closed for
  dialect variants and value-converting decorators.
- `src/faststudio/introspection/_fields.py`: add type-specific flags (like
  `_max_length`, `_choices`, `_int_range`, the timezone/precision guards) and
  extend `json_default` if the wire format of defaults differs.

## 3. Contract + validation
- `src/faststudio/schemas/_dynamic.py`: add the write validator (to `_SIMPLE`
  or `_BUILDERS`), as strict as the database. `test_every_writable_field_type_has_a_validator`
  fails until you do.
- The contract's field type in `src/faststudio/schemas/contract.py` must reuse
  `introspection._types.FieldType` (single source of truth); never redeclare it.
- `src/faststudio/schemas/_dynamic.py`: map to the Pydantic input type
  (strict where possible) and to the serializer for the wire format.
- Run the `api-contract-sync` skill.

## 4. Frontend
- `frontend/src/components/fields/`: form widget (labelled, accessible,
  keyboard operable) and table cell renderer; register both in the field
  registry keyed by `FieldType`.
- Zod schema builder: add the case so client-side validation mirrors the
  server (server remains authoritative).
- Vitest: widget renders, edits, shows validation error; cell formats value.
  TypeScript exhaustiveness check on `FieldType` must compile.

## 5. Finish
- Add the column to `examples/basic` models so E2E exercises it.
- Run the full check suite (see `CLAUDE.md`), update CHANGELOG ("Added"),
  request code-reviewer review.

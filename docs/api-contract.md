# API contract (v1)

Base path: `{base_url}/api/v1` (default `/admin/api/v1`). Metadata
`schema_version`: `"1"`. The contract is defined by Pydantic models in
`faststudio.schemas`, exported to `schemas/contract.schema.json` and generated
into `frontend/src/api/contract.gen.ts` (ADR-0007). CI fails if they drift.

## Endpoints

| Method | Path | Session | CSRF | Success |
|---|---|---|---|---|
| POST | `/auth/login` | – | yes (anonymous token) | 200 `{user}` + cookies |
| POST | `/auth/logout` | yes | yes | 204 |
| GET | `/auth/me` | yes | – | 200 `{user}` |
| GET | `/meta` | yes | – | 200 `MetaResponse` |
| GET | `/models/{identity}/items` | yes | – | 200 `ListResponse` |
| GET | `/models/{identity}/items/{pk}` | yes | – | 200 `Row` |
| POST | `/models/{identity}/items` | yes | yes | 201 `Row` |
| PATCH | `/models/{identity}/items/{pk}` | yes | yes | 200 `Row` |
| DELETE | `/models/{identity}/items/{pk}` | yes | yes | 204 |
| GET | `/models/{identity}/fields/{field}/choices` | yes | – | 200 `ChoicesResponse` |

### List query parameters

| Param | Rules |
|---|---|
| `page` | integer ≥ 1 (default 1) |
| `page_size` | 1 … `max_page_size` (default `ModelAdmin.page_size`) |
| `q` | free text; `ILIKE` across `search_fields` with bound parameters; ignored if none declared |
| `ordering` | `field` or `-field`, comma-separated; each must be sortable and allowlisted |
| `filter[field]` | `field ∈ list_filter`; value must be `true`/`false`/`null` (boolean) or a declared choice |

Unknown parameters or values outside these rules return `400 invalid_query`.

## Shapes

```jsonc
// Row
{ "pk": "42", "data": { "email": "a@b.c", "team_id": 3 }, "labels": { "team_id": "Core" } }

// ListResponse
{ "items": [Row], "total": 120, "page": 1, "page_size": 25 }

// MetaResponse
{
  "schema_version": "1", "version": "0.1.0", "title": "FastStudio", "show_powered_by": true,
  "user": { "id": "1", "username": "admin" },
  "models": [{
    "identity": "users", "name": "User", "name_plural": "Users", "icon": "users",
    "pk_field": "id",
    "list_display": ["id", "email"], "search_fields": ["email"],
    "list_filter": [{ "field": "is_active", "kind": "boolean", "choices": [] }],
    "ordering": ["-created_at"], "sortable_fields": ["id", "email", "created_at"],
    "page_size": 25,
    "permissions": { "create": true, "edit": true, "delete": false },
    "fields": [FieldMeta]
  }]
}

// FieldMeta
{
  "name": "team_id", "label": "Team", "type": "foreign_key",
  "nullable": true, "required": false, "readonly": false, "create_only": false,
  "primary_key": false, "default": null, "has_default": false,
  "max_length": null, "min_value": -2147483648, "max_value": 2147483647,
  "choices": null,
  "relation": { "target_identity": "teams", "target_field": "id", "value_type": "integer" },
  "timezone": null, "precision": null, "scale": null, "help_text": null
}
```

## Errors

Every error response, including 404 and 500, has this body:

```json
{ "error": { "code": "validation_error", "message": "Invalid input.", "details": [ { "loc": ["email"], "msg": "...", "type": "string_too_long" } ] } }
```

| Status | `code` | When |
|---|---|---|
| 400 | `invalid_query` | bad list parameter / non-allowlisted field |
| 401 | `not_authenticated` | missing, tampered, expired or revoked session |
| 401 | `invalid_credentials` | login failed (always "Invalid username or password.") |
| 403 | `csrf_failed` | missing/invalid CSRF token or cross-origin request |
| 403 | `forbidden` | action disabled by `can_create` / `can_edit` / `can_delete` |
| 404 | `not_found` | unknown model identity, field or primary key |
| 409 | `conflict` | database integrity error (no SQL in the message) |
| 422 | `validation_error` | body failed validation, including unknown/readonly/excluded fields |
| 429 | `rate_limited` | too many login attempts (`Retry-After` header set) |
| 500 | `internal_error` | unexpected error (details logged server-side only) |

## Type mapping

Resolution order: single-column `ForeignKey` first, then `isinstance` on the
column type (`TypeDecorator.impl` unwrapped), most specific first.

| SQLAlchemy | `type` | Wire format | Input validation | Widget | Cell |
|---|---|---|---|---|---|
| single-column `ForeignKey` to the target's single-column primary key | `foreign_key` | target PK value | the FK column's own type (`relation.value_type`) | async combobox | label |
| `String(n)`, `Unicode` | `string` | string | `max_length=n` | text input | text |
| `Text`, `UnicodeText` | `text` | string | – | textarea | truncated |
| `Integer`, `SmallInteger`, `BigInteger` | `integer` | number | strict int | number | right-aligned |
| `Float`, `Double`, `Numeric(asdecimal=False)` | `float` | number | finite float | number | right-aligned |
| `Numeric` | `decimal` | string | `Decimal` | decimal text | right-aligned |
| `Boolean` | `boolean` | boolean | strict bool | switch | icon |
| `Date` | `date` | `YYYY-MM-DD` | date | date picker | date |
| `DateTime` | `datetime` | ISO 8601 | datetime | datetime-local | datetime |
| `Enum` (Python enum or strings) | `enum` | member name (string enums: the string) | one of names | select | badge |
| `JSON`, `JSONB` | `json` | any JSON | JSON value | JSON editor | code |
| `Uuid`, `postgresql.UUID` | `uuid` | string | UUID | text | monospace |
| `Time`, `Interval`, `LargeBinary`, `PickleType`, `ARRAY`, value-converting custom types, dialect-dependent types (`with_variant`, `TypeDecorator` overriding `load_dialect_impl`), anything else | `unsupported` | `str(value)` | read-only | read-only text | text |

Custom `TypeDecorator`s (and direct subclasses of built-in types) are
classified by their base type **only if they do not convert values**: no
override of `process_bind_param`, `process_result_value`, `bind_processor`,
`result_processor`, `bind_expression` or `column_expression`;
converting decorators (e.g. JSON stored in a VARCHAR, encrypted columns) are
`unsupported` because their Python type may differ from the storage type.
SQLAlchemy's emulated types (`Interval`, `PickleType`) are `unsupported` too.
A foreign key whose own column type is `unsupported` is `unsupported` (no
relation).

### Field flags

| Flag | Rule |
|---|---|
| `label` | `column_labels[field]`, else humanized attribute name (`created_at` → "Created at", relation `team_id` → "Team", `id` → "ID") |
| `nullable` | `Column.nullable` |
| `has_default` | the column has a Python `default` or a `server_default` |
| `default` | only for scalar Python defaults, in wire format (enum → member name, `decimal` and `Decimal`/dates/UUID → string). `null` for callables, server defaults, `unsupported` fields and fields with sensitive-looking names. **Published defaults are visible to every admin; do not put secrets in column defaults.** |
| `readonly` | in `readonly_fields` ∨ maintained by the database or SQLAlchemy (autoincrement, `Identity`, `Computed`, `Sequence`, `FetchedValue` server default, `onupdate`/`server_onupdate`, joined-inheritance subclass PK, polymorphic discriminator, `version_id_col`) ∨ `unsupported` ∨ a primary key that is not `create_only` |
| `create_only` | natural primary keys only: a PK with no default that is not generated (e.g. `code: String(2)`). Accepted on create, never on update. A PK with a default (`uuid4`) is `readonly`: clients never choose it. |
| `required` | not nullable ∧ no default ∧ not generated/managed ∧ not readonly |
| `min_value`, `max_value` | `integer` fields: portable ranges for `SmallInteger` (16-bit), `Integer` (32-bit), `BigInteger` (64-bit) |
| `max_length` | `String(n)` length, else `null` |
| `choices` | enums only: `[{value, label}]`, value = member name, label humanized (`IN_PROGRESS` → "In progress") |
| `relation` | single-column many-to-one foreign keys **to the target table's single-column primary key** only: `{target_identity, target_field, value_type}`; `target_identity` is `null` when the target model is not registered. Composite foreign keys and foreign keys to non-key columns are plain values. A foreign key to a table missing from the metadata is a `ConfigurationError`. |
| `timezone` | `DateTime(timezone=True)` → `true`; other datetimes `false`; non-datetimes `null` |
| `precision`, `scale` | `decimal` fields only |
| `help_text` | the column `comment`, **published to the browser** |

`exclude`d fields never appear in metadata, responses or accepted input.

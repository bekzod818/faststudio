# API contract (v1)

Base path: `{base_url}/api/v1` (default `/admin/api/v1`). Metadata
`schema_version`: `"1"`. The contract is defined by Pydantic models in
`faststudio/schemas/contract.py` (frozen, `extra="forbid"`), exported to
`src/faststudio/schemas/contract.schema.json` and generated into
`frontend/src/api/contract.gen.ts` (ADR-0007). Both artifacts are committed;
CI and pre-commit fail if they drift.

```bash
uv run python scripts/export_contract.py      # Pydantic -> JSON Schema
pnpm -C frontend gen:contract                 # JSON Schema -> TypeScript
uv run python scripts/export_contract.py --check && pnpm -C frontend check:contract
```

`FieldType` and `ErrorCode` are named definitions in the schema (and TypeScript
unions); the frontend must handle every `FieldType` (an exhaustive `switch`
is enforced by `tsc`). `LoginRequest` limits `username` to 150 characters
without control or bidi-override characters, and `password` to 1024
characters; the password never appears in `repr` or validation errors.

**Integers:** JavaScript represents integers exactly only up to ±(2^53 − 1).
Field bounds (`min_value`/`max_value`) and integer defaults outside that range
are published as `null` (the server still enforces bounds), and integer
*values* outside it are sent as strings in `Row.data`.

## Serving and routing

| Path under `base_url` | Behaviour |
|---|---|
| (exactly `base_url`) | 307 redirect to `base_url/` (query string kept) |
| `/api/...` | JSON API; unknown paths are JSON `404`, never the SPA. Cross-origin browser requests (any method) get `403 csrf_failed` (ADR-0008). |
| `/assets/...` | hashed SPA assets (`Cache-Control: public, max-age=31536000, immutable`); missing files are JSON `404` |
| `/<file>` | a top-level file of the built SPA (e.g. `favicon.svg`), matched exactly against an allowlist built at startup; never `index.html`, dotfiles or symlinks |
| anything else (GET/HEAD) | the SPA shell (history fallback); other methods get `405` |

The SPA shell is `index.html` with `<base href="{root}/">` and a JSON config
block, where `{root}` is the browser-visible mount root (any proxy
`root_path` + `base_url`). It is rendered per mount root and cached
(ADR-0005, ADR-0008):

```html
<script type="application/json" id="fs-config">{"api_url":"/admin/api/v1","base_url":"/admin","schema_version":"1","title":"FastStudio"}</script>
```

The block is the contract model `SpaConfig`; `<`, `>`, `&` and all non-ASCII
characters are `\u`-escaped so no value can close the element. It is public
(served before login), so it carries no version number. If the SPA is not
built, a `503` placeholder page is served.

## Authentication and CSRF

- The SPA shell (and any admin response) sets `faststudio_csrftoken` when the
  browser has no valid token; the SPA sends it back in `X-FastStudio-CSRF`.
- `POST /auth/login` accepts an anonymous token; on success it sets
  `faststudio_session` and a new token bound to the session.
- Every other unsafe request needs the session-bound token. Missing or wrong
  tokens get `403 csrf_failed` before routing (also for unknown paths).
- `POST /auth/logout` clears the session and issues a new anonymous token.
- Any `401 not_authenticated` caused by an invalid session also clears it.

Record URLs carry the primary key URL-encoded as one path segment. Keys that
are exactly `.` or `..` are dot segments by the URL standard and cannot be
addressed; avoid them as natural keys.

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
| `page` | integer 1 … 100 000 (default 1) |
| `page_size` | 1 … `max_page_size` (default `ModelAdmin.page_size`) |
| `q` | ≤ 200 characters, no control characters, trimmed; case-insensitive *contains* across `search_fields` with bound parameters; `%`, `_` and `\` match literally; ignored if none declared |
| `ordering` | `field` or `-field`, comma-separated, at most 5, no repeats; each must be in `sortable_fields`; an empty value is `400` (omit the parameter for the default). The primary key is appended as a tie-breaker. Default: `ModelAdmin.ordering`, else primary key |
| `filter[field]` | `field ∈ list_filter`; value `true`/`false` (boolean), a declared choice value (enum), or `null` if the column is nullable |

Any other parameter, a repeated parameter or a value outside these rules
returns `400 invalid_query`; messages name the parameter, never the value.

### Rows

- `data` holds the `list_display` fields in lists and every visible field when
  retrieving one record.
- `labels` maps each foreign-key field to the display label of the referenced
  record when its model is registered. The label is the target's first
  visible string/text field (`list_display` first), falling back to its
  primary key (also used when the value is empty); `__str__` is never used.
  Labels are at most 200 characters. With inheritance, only rows of the
  registered target class are labelled.
- **Many-to-many fields** (`ModelAdmin.many_to_many`, ADR-0010) appear only
  when retrieving one record:
  - `data[field]` is the list of linked target keys in key order, in the same
    wire form as foreign keys;
  - `many_labels[field]` maps each key (as a string) to its label, which falls
    back to the key when the target model is not registered;
  - at most `max_items` keys are returned. When more links exist, the field
    is listed in `truncated` and is read-only for that record.

  `many_labels` and `truncated` are always present, and empty in lists and
  for models without many-to-many fields.
- Integers outside ±(2^53 − 1) are strings, also when nested inside JSON values.
- Unsupported values are shown as text (binary data as `<N bytes>`, other
  values truncated to 200 characters).

### Choices

`GET /models/{identity}/fields/{field}/choices?page=&q=` works only for
foreign-key and many-to-many fields whose target model is registered
(otherwise `404`). It
returns 20 options per page ordered by label, each `{value: <target pk as
string>, label}`. `q` searches the target's `search_fields`, or its label field
when it has none (and is ignored if the label is the primary key). Only rows
of the registered target class are offered (joined and single-table
inheritance respected).

### Writes

`POST /models/{identity}/items` (201), `PATCH /models/{identity}/items/{pk}`
(200) and `DELETE /models/{identity}/items/{pk}` (204) respond with the full
`Row` (all visible fields) after the database round trip.

- **Permissions:** `can_create` / `can_edit` / `can_delete` false ⇒ `403
  forbidden`, checked before the body is read.
- **Body:** `Content-Type: application/json` (anything else ⇒ `422` with
  `type: "content_type"`), a JSON object, at most 1 MiB
  (`413 payload_too_large`, also enforced while streaming).
- **Fields:** only fields the generated write schema allows. Create accepts
  writable fields plus `create_only` natural keys; update accepts writable
  fields only (never primary keys). Readonly, excluded, unknown fields ⇒
  `422 validation_error` with `type: "extra_forbidden"`; nothing is written.
  Omitted fields are left untouched (create uses column defaults).
- **Values** (strict, at least as strict as the database):
  - `null` only for nullable fields;
  - strings within the column length and at most 65 535 characters, no NUL;
  - integers as JSON integers or ASCII digit strings, within the column range;
  - floats: finite JSON numbers (no strings or booleans);
  - decimals within precision/scale (strings or numbers);
  - booleans: `true`/`false` only;
  - enums: member names;
  - dates and datetimes: ISO 8601 strings only (no timestamps). A naive column
    rejects timezone-aware values; a timezone-aware column treats naive values
    as UTC;
  - UUIDs: canonical `8-4-4-4-12` form;
  - JSON: finite numbers, integers within ±(2^53 − 1), no NUL in strings or keys.
    Integers beyond ±(2^53 − 1) are *read* as strings (see Rows), so saving
    such a JSON value from the UI stores them as strings.
- **Foreign keys:** a non-null value must reference an existing row, else
  `422` with `type: "foreign_key"`.
- **Delete:** refused with `409` while an ORM `relationship()` the delete
  would touch still has related rows: one-to-many, many-to-many, or
  many-to-one with a `delete` cascade. This keeps ORM cascades from changing
  rows of other models; database foreign-key rules also give `409`.
- **Account safety** (ADR-0009): when the auth backend's user model is
  registered (`ModelUserBackend`), an admin cannot change their own sign-in
  flags (`is_active` / `is_admin` as configured) to a different value or delete
  their own row (`409 self_lockout`; re-sending the current values is fine),
  and no write may remove the last active admin (`409 last_admin`, checked in
  the write's transaction). Nothing is written when a write is refused.
  Registering another mapping of the user model's table (a base class or a
  second class on the same table) fails at startup. Custom `AuthBackend`s are
  not covered unless they implement the guard capability (public in v0.2).
- **Many-to-many fields:** a write replaces the whole set with the sent list
  of keys (`[]` clears it), in the same transaction as the rest of the write.
  It is refused with `422` when:
  - a key does not exist (`type: "foreign_key"`);
  - a key is repeated (`value_error`) or has the wrong type;
  - there are more than `max_items` keys (`too_long`);
  - the record already has more links than `max_items` (`truncated`);
  - the field is readonly (`extra_forbidden`), or the value is `null`.

  The record is locked for the write, so concurrent link writes to the same
  record are serialized: they never merge and never store a duplicate pair.
  Only missing links are inserted. A lost race (a foreign-key violation, a
  duplicate pair written by other code when the association table has a
  unique pair, or a serialization failure) is `409 conflict`, never `500`.
- **Delete and many-to-many links (ADR-0010 §6):** deleting a record first
  removes the links of its opted-in many-to-many fields, and of opted-in
  fields of other registered models pointing at it, in the same
  transaction. Relationships that are not opted in keep the rule below
  (`409` while they have related rows).
- **Database errors:** integrity errors ⇒ `409 conflict`; a write that loses
  a lock or snapshot race to a concurrent request (SQLite busy/locked,
  serialization failure, deadlock), or updates a row another request deleted
  meanwhile ⇒ `409 conflict`; data errors (value
  rejected by the database) ⇒ `422` with `type: "database"`; anything else
  ⇒ `500`. The transaction is rolled back; no SQL or values are returned or
  logged by FastStudio.

## Shapes

```jsonc
// Row (many_labels and truncated: detail rows only, else empty)
{ "pk": "42", "data": { "email": "a@b.c", "team_id": 3, "tags": [1, 2] },
  "labels": { "team_id": "Core" }, "many_labels": { "tags": { "1": "news", "2": "tech" } },
  "truncated": [] }

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
    "fields": [FieldMeta],
    // Only on the model that holds the admins' accounts (ADR-0009), else null.
    // On the record whose pk equals user.id these fields are read-only and the
    // record cannot be deleted (the server answers 409 self_lockout).
    "account": { "protected_fields": ["is_active", "is_admin"] }
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
  // max_items: many_to_many fields only (the key limit), null otherwise
}
```

## Forward compatibility

`schema_version` stays `"1"` while changes are additive (ADR-0011): new keys
and new `FieldType` values may appear. Clients must ignore keys they do not
know and treat an unknown `FieldType` as `unsupported` (read-only text).
Removing or renaming a key, or changing its meaning, requires `"2"`.

## Errors

Every error response, including 404 and 500, has this body:

```json
{ "error": { "code": "validation_error", "message": "Invalid input.", "details": [ { "loc": ["email"], "msg": "...", "type": "string_too_long" } ] } }
```

`details` is a list of `{loc, msg, type}` for `validation_error` and `null`
for every other code. It never contains submitted *values*; `loc` may contain
client-supplied field names (e.g. an unknown body key), truncated to 64
characters, and at most 50 issues are returned.

| Status | `code` | When |
|---|---|---|
| 400 | `invalid_query` | bad list parameter / non-allowlisted field |
| 401 | `not_authenticated` | missing, tampered, expired or revoked session |
| 401 | `invalid_credentials` | login failed (always "Invalid username or password.") |
| 403 | `csrf_failed` | missing/invalid CSRF token or cross-origin request |
| 403 | `forbidden` | action disabled by `can_create` / `can_edit` / `can_delete` |
| 404 | `not_found` | unknown model identity, field or primary key; any unknown `/api/*` path (never the SPA) |
| 405 | `method_not_allowed` | wrong method on an API route, or a non-GET request to a UI path |
| 409 | `conflict` | database integrity error or lost lock race with a concurrent write (no SQL in the message) |
| 409 | `self_lockout` | the signed-in admin tried to change their own sign-in flags or delete their own account |
| 409 | `last_admin` | the write would leave no active admin |
| 413 | `payload_too_large` | request body over 1 MiB |
| 422 | `validation_error` | body failed validation, including unknown/readonly/excluded fields |
| 429 | `rate_limited` | too many login attempts (`Retry-After` header set) |
| 500 | `internal_error` | unexpected error (details logged server-side only) |

## Type mapping

Resolution order: single-column `ForeignKey` first, then `isinstance` on the
column type (`TypeDecorator.impl` unwrapped), most specific first.

| SQLAlchemy | `type` | Wire format | Input validation | Widget | Cell |
|---|---|---|---|---|---|
| single-column `ForeignKey` to the target's single-column primary key | `foreign_key` | target PK value | the FK column's own type (`relation.value_type`) | async combobox | label |
| `relationship()` over a plain association table, listed in `ModelAdmin.many_to_many` | `many_to_many` | list of target PK values | each key like the target PK; distinct; at most `max_items` | read-only (multi-select in v0.2 M16) | not listable |
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
| `min_value`, `max_value` | `integer` fields: portable ranges for `SmallInteger` (16-bit), `Integer` (32-bit), `BigInteger` (64-bit). The same ranges bound integer keys in URLs, so a plain `Integer` primary key above 2^31 − 1 (possible on SQLite) is not addressable: declare it `BigInteger` |
| `max_length` | `String(n)` length, else `null` |
| `choices` | enums only: `[{value, label}]`, value = member name, label humanized (`IN_PROGRESS` → "In progress") |
| `relation` | single-column many-to-one foreign keys **to the target table's single-column primary key** only: `{target_identity, target_field, value_type}`; `target_identity` is `null` when the target model is not registered. Composite foreign keys and foreign keys to non-key columns are plain values. A foreign key to a table missing from the metadata is a `ConfigurationError`. |
| `timezone` | `DateTime(timezone=True)` → `true`; other datetimes `false`; non-datetimes `null` |
| `precision`, `scale` | `decimal` fields only |
| `help_text` | the column `comment`, **published to the browser** |

`exclude`d fields never appear in metadata, responses or accepted input.

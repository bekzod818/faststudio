# ADR-0010: Many-to-many fields

- Status: Proposed
- Date: 2026-11-24
- Amends: the v0.1 delete rule (docs/api-contract.md "Delete"). Plan: docs/plans/v0.2.md §2

## Context

v0.1 exposes columns only; relationships appear only as many-to-one foreign
keys. `contrib.auth` (ADR-0011) and common host models (tags, categories)
need many-to-many editing. Exposing new writable fields on upgrade must not
happen silently.

## Decision

1. **Plain secondaries only.** Sides are detected from `synchronize_pairs`
   and `secondary_synchronize_pairs`, so self-referential relationships
   work. The secondary has exactly two foreign-key columns, each referencing
   the single-column primary key of one side; any other column has a server
   or Python default. Other relationships listed in the option fail at
   `register()`.
2. **Opt-in.** `ModelAdmin.many_to_many = ("tags",)`; unlisted relationships
   stay invisible. `exclude` and `readonly_fields` apply, and `viewonly=True`
   makes the field readonly. These fields are not usable in `list_display`,
   search, filters or ordering in v0.2.
3. **Wire format.**
   - The value is a list of target primary keys, in foreign-key wire form.
   - Detail rows carry `many_labels[field][pk]` and `truncated: [field]`.
   - List rows omit M2M fields.
   - `FieldType` gains `"many_to_many"`, and `FieldMeta.max_items` is new.
4. **Bounds** (`MAX_RELATED_ITEMS = 500`):
   - Reads use an explicit query with `LIMIT max_items + 1`; there is no
     lazy loading under asyncio.
   - When more links exist, the field is listed in `truncated`, and the
     server refuses writes to it (`422`).
   - A write with more than `max_items` keys is also `422`.
5. **Writes replace the set** in the write's transaction.
   - Added keys must exist (`422 foreign_key`).
   - Only association rows change.
   - The account guard and the escalation rules (ADR-0011) see the field in
     `WriteIntent.changes` as a list of primary keys.
6. **Delete-rule amendment.** Deleting a row removes its plain-secondary
   links in the same transaction. The v0.1 rule (409 while a relationship
   has related rows) stays for all other relationships.
7. **The picker** reuses `GET /fields/{field}/choices`: searchable,
   paginated, with the v0.1.1 offset cap. The authorization rules for
   choices are in ADR-0011.

## Alternatives considered

- **Automatic exposure like columns:** an upgrade would silently expose new
  writable fields on host models.
- **Link endpoints per pair:** more requests, and no atomic replace.
- **Association objects now:** they need inline forms (v0.3).

## Consequences

- No behaviour change on upgrade until a host opts in.
- A contract value is added. This is additive (ADR-0011 versioning rule).

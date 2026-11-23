---
name: add-modeladmin-option
description: How to add a new ModelAdmin option to FastStudio safely - naming, defaults, startup validation, metadata exposure, server-side enforcement, SPA support, docs and tests. Use whenever a new class attribute on ModelAdmin is proposed.
---

# Add a ModelAdmin option

`ModelAdmin` attributes are **public API**. Treat each one as permanent.

## 1. Design (architect review)
- Name follows Django Admin precedent where one exists (`list_per_page` →
  we use `page_size`; keep our existing names consistent).
- Type it as `ClassVar[...]` with an immutable default (`()`, not `[]`).
- Backwards compatible default: existing ModelAdmins must behave identically.
- Decide: is it UI-only, server-enforced, or both? **Anything that restricts
  access or data must be enforced on the server**, never only in the SPA.
- If it relaxes a security property (e.g. exposing more fields), get
  security-reviewer sign-off and update `docs/threat-model.md`.

## 2. Tests first
- `tests/unit/test_model_admin_validation.py`: invalid values raise
  `ConfigurationError` at `admin.register()` with a message naming the class,
  option and bad value.
- Integration tests for server-side enforcement (allowed and rejected path).
- Metadata test asserting the option appears in `/api/v1/meta` if exposed.

## 3. Implement
- Declare in `src/faststudio/model_admin.py` with a docstring.
- Validate in `src/faststudio/registry.py` against the mapper (field names
  exist, types compatible, no overlap conflicts such as `exclude` ∩
  `list_display`).
- Store the resolved value on the internal registered-model object; request
  code reads only resolved values, never the raw class attribute.
- Expose via `ModelMeta` in `schemas/contract.py` if the SPA needs it, then
  run `api-contract-sync`.

## 4. SPA
- Consume from metadata; add Vitest coverage.

## 5. Docs
- `docs/configuration.md` ModelAdmin table, README if user-facing headline,
  CHANGELOG "Added".

---
name: api-contract-sync
description: Regenerate the JSON Schema and TypeScript types from FastStudio's Pydantic API contract and verify both sides compile. Use after any change to src/faststudio/schemas/ or when CI reports contract drift.
---

# API contract sync (ADR-0007)

Source of truth: Pydantic models in `src/faststudio/schemas/contract.py`.

```bash
uv run python scripts/export_contract.py          # -> src/faststudio/schemas/contract.schema.json
pnpm -C frontend gen:contract                     # -> frontend/src/api/contract.gen.ts
git diff --stat -- src/faststudio/schemas/contract.schema.json frontend/src/api/contract.gen.ts
```

Then verify:

```bash
uv run mypy && uv run pytest tests/unit -q
pnpm -C frontend typecheck && pnpm -C frontend test
```

Checklist:
- [ ] Never hand-edit `contract.schema.json` or `contract.gen.ts`.
- [ ] Output is deterministic (run twice → no diff).
- [ ] Removing/renaming a field or changing a type is **breaking**: needs an
      ADR and a `schema_version` bump; adding optional fields is not.
- [ ] `docs/api-contract.md` updated to match.
- [ ] Both generated files committed in the same commit as the schema change.

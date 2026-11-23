## Summary

<!-- What does this change and why? Link issues with "Closes #123". -->

## Type

- [ ] feat
- [ ] fix
- [ ] docs
- [ ] refactor / chore / build / ci
- [ ] Breaking change (needs an ADR in docs/adr/)

## Checklist

- [ ] Tests added or updated first; `uv run pytest` passes and coverage stays >= 90%
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy` pass
- [ ] Frontend: `pnpm -C frontend lint && pnpm -C frontend test` pass (if touched)
- [ ] API contract regenerated if schemas changed (`api-contract-sync`)
- [ ] Security checklist reviewed (docs/threat-model.md); no protections weakened
- [ ] Docs and `CHANGELOG.md` ("Unreleased") updated

# ADR-0007: Generate frontend types from the Pydantic contract

- Status: Accepted
- Date: 2026-11-23

## Context

Backend and frontend must agree on API shapes; hand-written duplicates drift.

## Decision

Pydantic models in `faststudio.schemas` are the single source of truth.
`scripts/export_contract.py` writes `src/faststudio/schemas/contract.schema.json`
(deterministic, sorted). `pnpm -C frontend gen:contract` runs
`json-schema-to-typescript` to produce `frontend/src/api/contract.gen.ts`.
Both files are committed. CI regenerates them and fails on any diff.

## Consequences

- Type errors surface at build time on both sides.
- Contract changes show up clearly in code review.
- Generated files are excluded from lint/format.

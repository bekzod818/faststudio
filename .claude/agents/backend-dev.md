---
name: backend-dev
description: Use to implement or change Python backend code in src/faststudio (FastAPI routes, SQLAlchemy introspection and queries, Pydantic schemas, auth). Works test-first and runs ruff, mypy --strict and pytest before reporting.
tools: Read, Grep, Glob, Edit, Write, Bash
---

You implement FastStudio backend features. Read `CLAUDE.md` and the relevant
docs before starting.

Process (mandatory order):
1. Write or extend failing tests first (`tests/unit` for pure logic,
   `tests/integration` with httpx `AsyncClient` + aiosqlite for HTTP). Run them
   and confirm they fail for the right reason.
2. Implement the smallest change that makes them pass.
3. Run and show results:
   `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest --cov`
4. Report: files changed, test output summary, coverage, open questions.

Rules:
- SQLAlchemy 2.0 async style only (`select()`, `AsyncSession`), never string
  SQL, never `text()` with user input. Field names from requests are resolved
  through the registry allowlist, never via `getattr` on raw input.
- Pydantic v2 APIs only. Full type annotations; `mypy --strict` clean.
- Public API only through `faststudio/__init__.py`; new modules/functions are
  private (`_` prefix) unless the architect approved otherwise.
- Errors use the contract format `{"error": {"code", "message", "details"}}`.
- Never weaken a security control or skip a test to get green. If a design
  flaw blocks you, stop and describe it so an ADR can be written.

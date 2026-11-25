# Contributing to FastStudio

Thanks for helping! This guide covers setup, workflow and the quality bar.

## Prerequisites

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22 or 24 LTS and [pnpm](https://pnpm.io/) (only needed to work on the UI or build wheels)

## Setup

```bash
git clone https://github.com/bekzod818/faststudio && cd faststudio
uv sync                                 # Python env + dev tools
pnpm -C frontend install                # frontend deps
uv run pre-commit install               # git hooks (incl. commit-msg)
pnpm -C frontend build                  # build the SPA into src/faststudio/static
```

## Everyday commands

| Task | Command |
|---|---|
| Python tests + coverage | `uv run pytest --cov` |
| PostgreSQL tests (throwaway database; skipped without the variable) | `FASTSTUDIO_TEST_POSTGRES_URL=postgresql+asyncpg://user@localhost/faststudio_test uv run pytest -m postgres` |
| Lint / format | `uv run ruff check . && uv run ruff format .` |
| Type check | `uv run mypy` |
| Frontend lint / test | `pnpm -C frontend lint && pnpm -C frontend test` |
| Frontend dev server | `pnpm -C frontend dev` |
| E2E | `pnpm -C frontend build && pnpm -C frontend test:e2e` (starts `examples/basic --ephemeral`) |
| Example app | `uv run python -m examples.basic` (see `examples/basic/README.md`) |
| Build wheel | `pnpm -C frontend build && uv build && uv run python scripts/verify_wheel.py dist/*.whl` |

## Workflow

1. Open or pick an issue; for anything touching the public API, discuss first.
   Breaking or architectural changes need an ADR in `docs/adr/`.
2. Branch from `main` (`feat/...`, `fix/...`, `docs/...`).
3. **Write tests first**, then the implementation.
4. Keep commits small and use [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat(api): add choices endpoint`). The commit-msg hook enforces this.
5. Update docs and `CHANGELOG.md` under **Unreleased**.
6. Open a PR using the template. CI must be green.

## Quality bar

- `mypy --strict` clean, no `type: ignore` without an error code and a reason.
- Backend coverage ≥ 90 %; security-relevant code is tested for both the
  allowed and the rejected path.
- Never weaken a security check or skip a test to make CI pass.
- `tests/compat/v0_1_0/` is a frozen copy of the v0.1.0 README quickstart and
  `examples/basic`. Never edit it: `tests/compat/test_v0_1_0.py` checks its
  hashes and proves that v0.1 apps keep working unchanged.
- Tests dispose every engine and close every connection they open; engine
  fixtures are function-scoped and dispose the engine in their teardown. A
  guard in `tests/conftest.py` (`tests/_leaks.py`) fails the test that leaves
  an aiosqlite connection open, instead of a random later test.
- Never commit `src/faststudio/static/` (built output).
- Public API changes are deliberate: everything not exported from
  `faststudio/__init__.py` is private.

## Recommended branch protection for `main`

Maintainers should configure (Settings → Rules → Rulesets):

- Require a pull request before merging, with at least 1 approval and
  dismissal of stale approvals on new commits.
- Require status checks to pass: `Lint (Python)`, `Typecheck (mypy --strict)`,
  `Test (Python 3.11/3.12/3.13)`, `Security scans`, `Frontend (lint, test, build)`,
  `Build wheel + sdist`, `Wheel smoke (...)`, `E2E (Playwright)`, `Analyze (...)`.
- Require branches to be up to date before merging.
- Require conversation resolution and linear history (squash or rebase merges).
- Block force pushes and deletions; include administrators.
- Restrict who can push tags matching `v*` (release tags publish to PyPI).
- Protect the `pypi` and `testpypi` deployment environments with required
  reviewers.

## Releasing

Maintainers follow the `release` procedure in `.claude/skills/release/SKILL.md`
(TestPyPI first, then PyPI via a signed `vX.Y.Z` tag).

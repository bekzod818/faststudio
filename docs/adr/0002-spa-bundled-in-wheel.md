# ADR-0002: Ship the pre-built SPA inside the Python wheel

- Status: Accepted
- Date: 2026-11-23

## Context

Users of a Python admin library should not need Node.js. The UI is a React SPA.

## Decision

- `pnpm -C frontend build` writes to `src/faststudio/static/` (gitignored).
- `hatch_build.py` fails any wheel build when `static/index.html` is missing.
  Editable installs and `FASTSTUDIO_ALLOW_MISSING_FRONTEND=1` are exempt for
  development only.
- The sdist includes `static/`, so building a wheel from the sdist works
  without Node.
- `scripts/verify_wheel.py` runs in CI and release to assert the assets
  (and no source maps) are present.

## Consequences

- Release and CI pipelines need Node + pnpm; users never do.
- Wheel size grows by the bundle size (target < 500 kB gzipped).
- Built files are never committed (pre-commit hook enforces).

---
name: release
description: The full FastStudio release procedure - version bump, changelog, local verification, TestPyPI dry run, then PyPI via tag with Trusted Publishing. Use when preparing any release. Publishing, tagging and pushing always need the maintainer's explicit confirmation.
---

# Release procedure

**Rule: never run `git push`, `git tag`, `gh release` or any publish command
without the maintainer explicitly confirming that exact step.**

## 1. Prepare (on a `release/vX.Y.Z` branch)
1. Choose version (SemVer; 0.x breaking → minor bump). Pre-releases:
   `X.Y.ZrcN`.
2. Set `__version__` in `src/faststudio/__init__.py`.
3. CHANGELOG: move "Unreleased" to `## [X.Y.Z] - YYYY-MM-DD`, update links.
   Pin README image URLs (`raw.githubusercontent.com/.../main/...`) to the
   tag `vX.Y.Z` so the PyPI page never changes with `main`.
4. Commit: `chore(release): prepare vX.Y.Z`. Open PR, wait for green CI, merge.

## 2. Verify locally (show all output)
```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest --cov
pnpm -C frontend install --frozen-lockfile
pnpm -C frontend lint && pnpm -C frontend test && pnpm -C frontend build
rm -rf dist && uv build && uv run python scripts/verify_wheel.py dist/*.whl
uvx --from twine==7.0.0 twine check --strict dist/*          # PyPI metadata + README rendering
uv venv /tmp/fs-rel && uv pip install --python /tmp/fs-rel/bin/python dist/*.whl pytest pytest-asyncio httpx aiosqlite
FASTSTUDIO_WHEEL_SMOKE=1 /tmp/fs-rel/bin/python -m pytest tests/e2e -m e2e -p no:cacheprovider
uv run python scripts/changelog_notes.py X.Y.Z
```

## 3. TestPyPI (after confirmation)
```bash
gh workflow run release.yml -f target=testpypi --ref main
gh run watch
```
Then in a clean venv:
`pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ faststudio==X.Y.Z`
and run the README quickstart.

## 4. PyPI (after confirmation)
```bash
git switch main && git pull --ff-only
git tag -s vX.Y.Z -m "FastStudio vX.Y.Z"
git push origin vX.Y.Z
```
The tag triggers `release.yml`: build → publish to PyPI (environment `pypi`,
needs reviewer approval) → GitHub release with changelog notes.

## 5. After
- Point README image URLs back to `main`.
- Verify https://pypi.org/project/faststudio/ and the GitHub release.
- Add a fresh `## [Unreleased]` section; bump `__version__` to the next
  `.dev0`.

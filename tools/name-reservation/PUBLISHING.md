# Publishing the 0.0.1 name-reservation release

This placeholder reserves `faststudio` on TestPyPI and PyPI. You (the
maintainer) run every command below; nothing here is automated.

Real releases (0.1.0+) use `.github/workflows/release.yml` with Trusted
Publishing and **no API tokens**. The 0.0.1 placeholder is the only upload
done by hand, with a short-lived token that you delete afterwards.

## 0. Prerequisites

- Accounts on <https://test.pypi.org> and <https://pypi.org> (separate
  accounts), both with **2FA enabled** (required for uploading).
- The GitHub repository `bekzod818/faststudio` exists.

## 1. Build and check

```bash
cd tools/name-reservation
rm -rf dist && uv build
uvx twine check dist/*
```

Expected: `faststudio-0.0.1.tar.gz` and `faststudio-0.0.1-py3-none-any.whl`,
both `PASSED`.

## 2. Upload to TestPyPI

1. TestPyPI → Account settings → API tokens → **Add API token**,
   scope "Entire account" (the project does not exist yet). Copy it.
2. Upload (paste the token when prompted; do not put it in shell history or files):
   ```bash
   uv publish --publish-url https://test.pypi.org/legacy/ --username __token__ dist/*
   ```
3. Verify in a clean environment:
   ```bash
   uv venv /tmp/fs-check && uv pip install --python /tmp/fs-check/bin/python \
     --index-url https://test.pypi.org/simple/ faststudio==0.0.1
   /tmp/fs-check/bin/python -c "import faststudio; print(faststudio.__version__)"
   ```
4. **Delete the TestPyPI token** (Account settings → API tokens → Remove).

## 3. Upload to PyPI

Same as step 2 against PyPI:

```bash
uv publish --username __token__ dist/*
```

Then **delete the PyPI token** immediately.

## 4. Configure Trusted Publishing (for 0.1.0 and later)

### On PyPI
<https://pypi.org/manage/project/faststudio/settings/publishing/> → **Add a
new publisher** → GitHub:

| Field | Value |
|---|---|
| Owner | `bekzod818` |
| Repository name | `faststudio` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

### On TestPyPI
<https://test.pypi.org/manage/project/faststudio/settings/publishing/>, same
values but **Environment name** `testpypi`.

### On GitHub
Repository → Settings → Environments:

1. Create environment **`pypi`**: add yourself as *Required reviewer*;
   *Deployment branches and tags* → "Selected branches and tags" → add tag
   rule `v*.*.*`.
2. Create environment **`testpypi`**: required reviewer optional;
   deployment branches → `main`.

Settings → Rules → Rulesets → new **tag** ruleset targeting `v*` that restricts
creation/deletion to maintainers.

### Lock down the PyPI project
- PyPI project settings → ensure no API tokens remain scoped to `faststudio`.
- Optional: add a second owner/maintainer with 2FA for bus-factor.

## 5. Verify Trusted Publishing works

Before tagging 0.1.0, run the TestPyPI path from GitHub (Actions → Release →
Run workflow → target `testpypi`) once a `0.1.0rc1` or `.devN` version is on
`main`. A successful run proves the OIDC configuration end to end.

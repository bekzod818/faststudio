#!/usr/bin/env bash
# PostToolUse hook: format + lint the single file Claude just edited.
# Fast by design: only touches one file; never runs test suites.
set -euo pipefail

file=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')
[[ -z "$file" || ! -f "$file" ]] && exit 0

root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$root"

case "$file" in
  "$root"/src/faststudio/static/*) exit 0 ;;  # built output, never formatted
  *.py)
    uv run --quiet ruff format "$file" >/dev/null
    # Surface remaining lint errors to Claude (exit 2 feeds stderr back).
    if ! out=$(uv run --quiet ruff check --fix "$file" 2>&1); then
      echo "$out" >&2
      exit 2
    fi
    ;;
  "$root"/frontend/*.ts | "$root"/frontend/*.tsx | "$root"/frontend/*.js)
    rel="${file#"$root"/frontend/}"
    (cd frontend && pnpm exec prettier --write --log-level warn "$rel")
    if ! out=$(cd frontend && pnpm exec eslint --max-warnings=0 "$rel" 2>&1); then
      echo "$out" >&2
      exit 2
    fi
    ;;
  "$root"/frontend/*.css | "$root"/frontend/*.json)
    rel="${file#"$root"/frontend/}"
    (cd frontend && pnpm exec prettier --write --log-level warn "$rel")
    ;;
esac
exit 0

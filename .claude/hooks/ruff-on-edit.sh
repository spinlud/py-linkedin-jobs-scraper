#!/usr/bin/env bash
# PostToolUse hook: applies ruff's fixes to the Python file Claude Code just edited, formats it,
# and hands what ruff cannot fix back to the agent (exit code 2 sends stderr to it).
set -uo pipefail

if ! file=$(jq -r '.tool_input.file_path // empty'); then
  echo 'The ruff hook needs jq to read which file was edited: install jq, or run npm run check.' >&2
  exit 2
fi

case "$file" in
  *.py | *.pyi) ;;
  *) exit 0 ;;
esac

[ -f "$file" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

# Fixes come first: the code they write is not formatted
report=$(uv run -q --locked ruff check --force-exclude --fix --output-format concise -q "$file" 2>&1)
status=$?
uv run -q --locked ruff format --force-exclude -q "$file" >/dev/null 2>&1

if [ "$status" -ne 0 ]; then
  printf 'ruff found what it cannot fix in %s:\n%s\n' "$file" "$report" >&2
  exit 2
fi

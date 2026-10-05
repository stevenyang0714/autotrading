#!/usr/bin/env bash
# PostToolUse hook (M0.4): after Claude Code edits web source or the glossary, regenerate the
# glossary types and type-check, so a metric without a complete glossary entry is caught at once
# instead of in CI. Exit 2 reports the failure back to Claude; edits to other files are ignored.
set -uo pipefail

file=$(jq -r '.tool_input.file_path // .tool_response.filePath // empty')
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

case "$file" in
  "$root"/apps/web/src/*.ts | "$root"/apps/web/src/*.tsx | "$root"/docs/glossary/glossary_seed.yaml) ;;
  *) exit 0 ;;
esac

# Node and pnpm come from nvm/corepack; load nvm when the hook shell has not.
if ! command -v pnpm >/dev/null 2>&1 && [ -s "$HOME/.nvm/nvm.sh" ]; then
  . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1
fi

cd "$root/apps/web" || exit 0
if ! out=$(node scripts/gen-glossary.mjs 2>&1 && NEXT_TELEMETRY_DISABLED=1 COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm -s typecheck 2>&1); then
  {
    echo "Glossary check failed after editing ${file#"$root"/}:"
    printf '%s\n' "$out" | grep -E 'error|Error|missing' | head -20
    echo "Fix: use a complete glossary term in <Metric termId=...>, or complete/add the term in docs/glossary/glossary_seed.yaml."
  } >&2
  exit 2
fi
exit 0

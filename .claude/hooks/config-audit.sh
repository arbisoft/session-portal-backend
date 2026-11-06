#!/bin/bash
# PostToolUse hook for Edit|Write: when Claude config changes, run the drift audit and feed errors back to Claude.
# Exit 2 sends stderr to Claude; exit 0 is silent. Warnings are not surfaced here (run the script to see them).

input=$(cat)
file=$(printf '%s' "$input" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))' 2>/dev/null)

case "$file" in
  */.claude/*|*/CLAUDE.md) ;;
  *) exit 0 ;;
esac

if ! output=$(python3 "${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/audit_config.py" 2>&1); then
  printf 'Claude config drift detected after editing %s:\n%s\n' "$file" "$output" >&2
  exit 2
fi
exit 0

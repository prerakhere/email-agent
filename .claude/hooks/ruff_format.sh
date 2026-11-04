#!/bin/bash
# PostToolUse hook: auto-format any Python file Claude just edited/wrote.
f=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')
case "$f" in
  *.py) cd "$CLAUDE_PROJECT_DIR" && uv run --quiet ruff format "$f" >/dev/null 2>&1 ;;
esac
exit 0

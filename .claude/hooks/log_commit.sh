#!/bin/bash
# PostToolUse hook (Bash): after a `git commit`, append "commit <hash>: <subject>" to WORKLOG.md.
# Idempotent (skips a hash already logged) and only fires for a commit made in the last MAX_AGE seconds.
cmd=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')
case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
MAX_AGE=${WORKLOG_HOOK_MAX_AGE:-120}
now=$(date +%s); ct=$(git log -1 --format=%ct 2>/dev/null) || exit 0
[ $((now - ct)) -le "$MAX_AGE" ] || exit 0
hash=$(git log -1 --format=%h); subject=$(git log -1 --format=%s)
[ -f WORKLOG.md ] || exit 0
grep -q "commit $hash:" WORKLOG.md && exit 0
printf -- '- [%s] commit %s: %s\n' "$(date +%Y-%m-%d)" "$hash" "$subject" >> WORKLOG.md
exit 0

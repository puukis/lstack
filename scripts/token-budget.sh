#!/usr/bin/env bash
# UserPromptSubmit hook: warn when context usage is high

source "${HOME}/.claude/scripts/os.sh"

command -v jq >/dev/null 2>&1 || exit 0

input="$(cat)"
pct="$(printf '%s' "${input}" | jq -r '.context_window.used_percentage // 0' 2>/dev/null || echo '0')"

# Ensure numeric
pct="${pct%%.*}"
pct="${pct:-0}"

if [ "${pct}" -ge 80 ] 2>/dev/null; then
    msg="WARNING: Context at ${pct}%. Compact immediately. Quality is already degrading."
    escaped="$(printf '%s' "${msg}" | "${PYTHON}" -c "import sys,json; print(json.dumps(sys.stdin.read()))" 2>/dev/null || printf '"%s"' "${msg}")"
    printf '{"additionalContext": %s}\n' "${escaped}"
elif [ "${pct}" -ge 60 ] 2>/dev/null; then
    msg="Context at ${pct}%. Run /compact now."
    escaped="$(printf '%s' "${msg}" | "${PYTHON}" -c "import sys,json; print(json.dumps(sys.stdin.read()))" 2>/dev/null || printf '"%s"' "${msg}")"
    printf '{"additionalContext": %s}\n' "${escaped}"
fi

exit 0

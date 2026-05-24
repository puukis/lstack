#!/usr/bin/env bash
# UserPromptSubmit hook: warn when context usage is high

source "${HOME}/.claude/scripts/os.sh"

command -v jq >/dev/null 2>&1 || exit 0

input="$(cat)"
pct="$(printf '%s' "${input}" | jq -r '.context_window.used_percentage // 0' 2>/dev/null || echo '0')"

# Ensure numeric
pct="${pct%%.*}"
pct="${pct:-0}"

_ctx_printed=0

if [ "${pct}" -ge 80 ] 2>/dev/null; then
    msg="WARNING: Context at ${pct}%. Compact immediately. Quality is already degrading."
    escaped="$(printf '%s' "${msg}" | run_python -c "import sys,json; print(json.dumps(sys.stdin.read()))" 2>/dev/null || printf '"%s"' "${msg}")"
    printf '{"additionalContext": %s}\n' "${escaped}"
    _ctx_printed=1
elif [ "${pct}" -ge 60 ] 2>/dev/null; then
    msg="Context at ${pct}%. Run /compact now."
    escaped="$(printf '%s' "${msg}" | run_python -c "import sys,json; print(json.dumps(sys.stdin.read()))" 2>/dev/null || printf '"%s"' "${msg}")"
    printf '{"additionalContext": %s}\n' "${escaped}"
    _ctx_printed=1
fi

# COMPLEXITY SIGNAL: nudge toward /orchestrate for large tasks
prompt_text="$(printf '%s' "${input}" | run_python -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get('prompt','')[:300])
except: print('')
" 2>/dev/null || echo '')"

if [ -n "${prompt_text}" ]; then
    complexity="$(run_python -c "
import sys
prompt = sys.argv[1].lower()

# Tier 3 signals
tier3 = any(w in prompt for w in [
    'refactor', 'rewrite', 'redesign', 'migrate',
    'add feature', 'new system', 'implement', 'build',
    'all files', 'entire', 'whole codebase', 'overhaul'
])
# Tier 2 signals
tier2 = any(w in prompt for w in [
    'and test', 'with tests', 'and review', 'and docs',
    'multiple', 'several files', 'few places', 'update all'
])

if tier3:
    print('tier3')
elif tier2:
    print('tier2')
else:
    print('tier1')
" "${prompt_text}" 2>/dev/null || echo 'tier1')"

    if [ "${_ctx_printed}" -eq 0 ] && [ "${complexity}" = "tier3" ]; then
        msg="This looks like a large task. Consider running /orchestrate first — it will evaluate whether sub-agents would help and ask before dispatching anything."
        escaped="$(run_python -c "import sys,json; print(json.dumps(sys.argv[1]))" "${msg}" 2>/dev/null)"
        printf '{"additionalContext": %s}\n' "${escaped}"
    elif [ "${_ctx_printed}" -eq 0 ] && [ "${complexity}" = "tier2" ]; then
        msg="This looks like a multi-part task. /orchestrate can break it into parallel workstreams if helpful — or just proceed here."
        escaped="$(run_python -c "import sys,json; print(json.dumps(sys.argv[1]))" "${msg}" 2>/dev/null)"
        printf '{"additionalContext": %s}\n' "${escaped}"
    fi
fi

exit 0

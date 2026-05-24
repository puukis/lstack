#!/usr/bin/env bash
# PreCompact hook: generate handover summary before context compaction

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"
LOG_DIR="${CLAUDE_DIR}/logs"

mkdir -p "${LOG_DIR}"

# Read stdin
input="$(cat)"

# Parse transcript_path and session_id
parsed="$(printf '%s' "${input}" | run_python - <<'PYEOF' 2>/dev/null || printf '\n'
import sys, json

data = {}
try:
    data = json.loads(sys.stdin.read())
except Exception:
    pass

print(data.get("transcript_path", ""))
print(data.get("session_id", ""))
PYEOF
)"

transcript_path="$(printf '%s' "${parsed}" | sed -n '1p')"
session_id="$(printf '%s' "${parsed}" | sed -n '2p')"

if [ -z "${transcript_path}" ]; then
    exit 0
fi

if [ -n "${LSTACK_INSIDE_HOOK:-}" ]; then
    printf '[%s] PRE_COMPACT claude skipped recursion-guard\n' "$(iso_now)" >> "${LOG_DIR}/compactions.log" 2>/dev/null || true
    exit 0
fi

# Determine output path
git_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "${git_root}" ]; then
    out_dir="${git_root}/.claude/memory"
    mkdir -p "${out_dir}"
    out_path="${out_dir}/handover.md"
else
    out_path="${CLAUDE_DIR}/memory/handover.md"
fi

# Spawn fresh subprocess to generate handover
# Using subshell to ensure isolation
(
    claude -p --allowedTools "" \
        "Read ${transcript_path}. Write a handover summary (max 300 words, plain text, no headers):
1. Current task and exact status
2. What was tried, what worked, what failed
3. Key decisions and why
4. Exact next step
Be specific. No padding." > "${out_path}" 2>/dev/null
) &

# Wait briefly for the subprocess — don't block compaction
sleep 2 2>/dev/null || true

# Log compaction
iso="$(iso_now)"
printf '[%s] %s -> %s\n' "${iso}" "${session_id}" "${out_path}" >> "${LOG_DIR}/compactions.log" 2>/dev/null || true

exit 0

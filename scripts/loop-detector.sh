#!/usr/bin/env bash
# Standalone loop detector — prints current loop state for lstack status

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"
LOG_DIR="${CLAUDE_DIR}/logs"

if [ ! -d "${LOG_DIR}" ]; then
    echo "No log directory found at ${LOG_DIR}"
    exit 0
fi

# Find all loop state files
loop_files="$(ls "${LOG_DIR}"/loop-*.json 2>/dev/null || true)"

if [ -z "${loop_files}" ]; then
    echo "No active loop state files."
    exit 0
fi

active_count=0
dead_count=0

printf '%-10s %-10s %-20s %s\n' "PID" "STATUS" "LAST_TOOL" "HASH"
printf '%s\n' "------------------------------------------------------------"

for f in ${loop_files}; do
    # Extract PID from filename
    pid="$(basename "${f}" | sed 's/loop-//;s/\.json//')"

    # Check if process is alive
    if kill -0 "${pid}" 2>/dev/null; then
        status="alive"
        active_count=$(( active_count + 1 ))
    else
        status="dead"
        dead_count=$(( dead_count + 1 ))
    fi

    # Get last entry
    last="$("${PYTHON}" - <<PYEOF 2>/dev/null || echo "unknown unknown"
import json
try:
    with open("${f}") as fh:
        entries = json.load(fh)
    if entries:
        last = entries[-1]
        print(last.get("tool", "?"), last.get("hash", "?"))
    else:
        print("empty", "-")
except Exception:
    print("error", "-")
PYEOF
)"
    last_tool="$(echo "${last}" | awk '{print $1}')"
    last_hash="$(echo "${last}" | awk '{print $2}')"

    printf '%-10s %-10s %-20s %s\n' "${pid}" "${status}" "${last_tool}" "${last_hash}"
done

echo ""
echo "Active: ${active_count}  Dead: ${dead_count}"

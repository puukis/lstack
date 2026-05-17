#!/usr/bin/env bash
# Stop hook: run project tests before allowing Claude to finish

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"
LOG_DIR="${CLAUDE_DIR}/logs"

mkdir -p "${LOG_DIR}"

# Read stdin
input="$(cat)"

# Check stop_hook_active
stop_hook_active="$(printf '%s' "${input}" | "${PYTHON}" -c "
import sys, json
data = {}
try:
    data = json.loads(sys.stdin.read())
except Exception:
    pass
print(str(data.get('stop_hook_active', False)).lower())
" 2>/dev/null || echo 'false')"

if [ "${stop_hook_active}" = "true" ]; then
    exit 0
fi

# Find test command from .claude/CLAUDE.md in git root
git_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
test_cmd=""

if [ -n "${git_root}" ] && [ -f "${git_root}/.claude/CLAUDE.md" ]; then
    # Extract line matching "test: <cmd>" under ## Build & Test section
    test_cmd="$(awk '
        /^## Build & Test/ { in_section=1; next }
        /^## / { in_section=0 }
        in_section && /^[[:space:]]*test:/ {
            sub(/^[[:space:]]*test:[[:space:]]*/, "")
            print
            exit
        }
    ' "${git_root}/.claude/CLAUDE.md" 2>/dev/null || true)"
fi

iso="$(iso_now)"

if [ -z "${test_cmd}" ]; then
    printf '[%s] STOP no-test-cmd found\n' "${iso}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    exit 0
fi

# Run test command with 60s timeout
test_output="$(cd "${git_root}" && timeout 60 bash -c "${test_cmd}" 2>&1)" && test_rc=0 || test_rc=$?

if [ "${test_rc}" -eq 0 ]; then
    printf '[%s] STOP tests-passed cmd="%s"\n' "${iso}" "${test_cmd}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    exit 0
else
    printf '[%s] STOP tests-failed cmd="%s" rc=%d\n' "${iso}" "${test_cmd}" "${test_rc}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    last_lines="$(printf '%s' "${test_output}" | tail -20)"
    printf 'Tests failed. Fix before finishing:\n%s' "${last_lines}"
    exit 2
fi

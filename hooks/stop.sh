#!/usr/bin/env bash
# Stop hook: run project tests and extract explicit lstack learning markers.

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"
LOG_DIR="${CLAUDE_DIR}/logs"
mkdir -p "${LOG_DIR}"

input="$(cat)"

fallback_test_command() {
    local git_root test_cmd
    git_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    test_cmd=""
    if [ -n "${git_root}" ] && [ -f "${git_root}/.claude/CLAUDE.md" ]; then
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

    if [ -z "${git_root}" ]; then
        printf '[%s] STOP no-git-root\n' "$(iso_now)" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    fi
    if [ -z "${test_cmd}" ]; then
        printf '[%s] STOP no-test-cmd found\n' "$(iso_now)" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
        return 0
    fi

    local test_output test_rc last_lines
    test_output="$(cd "${git_root}" && bash -c "${test_cmd}" 2>&1)" && test_rc=0 || test_rc=$?
    if [ "${test_rc}" -eq 0 ]; then
        printf '[%s] STOP tests-passed cmd=%s\n' "$(iso_now)" "${test_cmd}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
        return 0
    fi
    printf '[%s] STOP tests-failed cmd=%s rc=%d\n' "$(iso_now)" "${test_cmd}" "${test_rc}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    last_lines="$(printf '%s' "${test_output}" | tail -20)"
    printf 'Tests failed. Fix before finishing:\n%s' "${last_lines}"
    return 2
}

if [ "${PYTHON_AVAILABLE:-false}" != "true" ]; then
    printf '[%s] STOP python-unavailable learning skipped\n' "$(iso_now)" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    printf '[%s] STOP python_available=false\n' "$(iso_now)" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    fallback_test_command
    exit $?
fi

printf '[%s] STOP python_available=true provider=%s\n' "$(iso_now)" "$(python_provider_label)" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true

export LSTACK_INSIDE_HOOK=1
printf '%s' "${input}" | run_python "${CLAUDE_DIR}/scripts/stop_hook.py"
exit $?

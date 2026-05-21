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

notify_session_end() {
    local msg="${1:-Session complete}"
    case "${OS}" in
        macos)
            osascript -e "display notification \"${msg}\" with title \"lstack\"" \
                2>/dev/null || true
            ;;
        windows)
            powershell.exe -Command "
Add-Type -AssemblyName System.Windows.Forms
\$balloon = New-Object System.Windows.Forms.NotifyIcon
\$balloon.Icon = [System.Drawing.SystemIcons]::Information
\$balloon.Visible = \$true
\$balloon.ShowBalloonTip(3000, 'lstack', '${msg}', [System.Windows.Forms.ToolTipIcon]::Info)
" 2>/dev/null || true
            ;;
        linux)
            notify-send "lstack" "${msg}" 2>/dev/null || true
            ;;
    esac
}

run_learning_extraction() {
    local transcript_path
    transcript_path="$(printf '%s' "${input}" | "${PYTHON}" -c "
import sys, json
data = {}
try:
    data = json.loads(sys.stdin.read())
except Exception:
    pass
print(data.get('transcript_path', ''))
" 2>/dev/null || echo '')"

    [ -z "${transcript_path}" ] && return 0
    [ ! -f "${transcript_path}" ] && return 0
    command -v claude >/dev/null 2>&1 || return 0

    local patterns_file
    if [ -n "${git_root}" ] && [ -d "${git_root}/.claude/memory" ]; then
        patterns_file="${git_root}/.claude/memory/patterns.md"
    else
        patterns_file="${CLAUDE_DIR}/memory/patterns.md"
    fi

    local transcript_excerpt
    transcript_excerpt="$(tail -c 2000 "${transcript_path}" 2>/dev/null || true)"
    [ -z "${transcript_excerpt}" ] && return 0

    local learn_prompt
    learn_prompt="Session transcript (excerpt):
${transcript_excerpt}

---
Read this transcript. Extract at most 3 bullet points worth saving to
persistent memory. Only include items matching these criteria:
- Non-obvious bugs and their confirmed root cause
- APIs or libraries behaving differently than expected
- Project conventions discovered by reading code
- Commands or sequences that fixed a recurring error
- Architectural decisions and the reason they were made
Output ONLY the bullets, max 20 words each, plain text.
If nothing meets the criteria, output nothing."

    local learnings
    learnings="$(printf '%s' "${learn_prompt}" | claude -p 2>/dev/null || true)"
    [ -z "${learnings}" ] && return 0

    if [ ! -f "${patterns_file}" ]; then
        printf '# Patterns\n\n## Solutions\n' > "${patterns_file}"
    fi

    local iso_ts
    iso_ts="$(iso_now)"
    printf '%s' "${learnings}" | while IFS= read -r line; do
        [ -n "${line}" ] && printf '- [%s] %s\n' "${iso_ts}" "${line}" >> "${patterns_file}"
    done

    "${PYTHON}" - "${patterns_file}" <<'PYCAP' 2>/dev/null || true
import sys
path = sys.argv[1]
with open(path, 'r') as f:
    lines = f.readlines()
if len(lines) > 100:
    headers = [l for l in lines if not l.startswith('- [')]
    bullets = [l for l in lines if l.startswith('- [')]
    bullets = bullets[20:]
    with open(path, 'w') as f:
        f.writelines(headers[:3])
        f.writelines(bullets)
PYCAP

    local _learn_session_id _learn_project_raw _learn_project
    _learn_session_id="$("${PYTHON}" -c "import os; print(os.getppid())" 2>/dev/null || echo "$$")"
    _learn_project_raw="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    _learn_project="$(to_native_path "${_learn_project_raw}" 2>/dev/null || echo "${_learn_project_raw}")"
    _learn_project="${_learn_project//\\//}"

    printf '%s' "${learnings}" | while IFS= read -r _learn_line; do
        [ -z "${_learn_line}" ] && continue
        local _learn_tags
        _learn_tags="$("${PYTHON}" -c "
import sys,os
sys.path.insert(0,os.path.expanduser('~/.claude/scripts'))
try:
  from db import extract_keywords
  print(','.join(extract_keywords(sys.argv[1])))
except: print('')
" "${_learn_line}" 2>/dev/null || echo '')"
        "${PYTHON}" "${DB_PY}" observe \
            "${_learn_session_id}" "${_learn_project}" "${_learn_line}" "${_learn_tags}" 2>/dev/null || true
    done

    printf '[%s] STOP learning-extracted\n' "$(iso_now)" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
}

if [ -z "${test_cmd}" ]; then
    printf '[%s] STOP no-test-cmd found\n' "${iso}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    run_learning_extraction
    notify_session_end "Session ended — memory updated"
    exit 0
fi

# Run test command with 60s timeout
test_output="$(cd "${git_root}" && timeout 60 bash -c "${test_cmd}" 2>&1)" && test_rc=0 || test_rc=$?

if [ "${test_rc}" -eq 0 ]; then
    printf '[%s] STOP tests-passed cmd="%s"\n' "${iso}" "${test_cmd}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true

    run_learning_extraction
    notify_session_end "Session ended — memory updated"

    exit 0
else
    printf '[%s] STOP tests-failed cmd="%s" rc=%d\n' "${iso}" "${test_cmd}" "${test_rc}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    last_lines="$(printf '%s' "${test_output}" | tail -20)"
    notify_session_end "Tests failed — session blocked"
    printf 'Tests failed. Fix before finishing:\n%s' "${last_lines}"
    exit 2
fi

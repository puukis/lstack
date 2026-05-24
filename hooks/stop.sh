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
try:
    d = json.loads(sys.stdin.read())
    print(d.get('transcript_path', ''))
except Exception:
    print('')
" 2>/dev/null || echo '')"

    # Convert Windows path (C:\... or C:/...) to POSIX for Git Bash
    if [ -n "${transcript_path}" ]; then
        transcript_path="$("${PYTHON}" -c "
import sys, re
p = sys.argv[1]
m = re.match(r'^([A-Za-z])[:/\\\\](.*)', p)
if m:
    drive = m.group(1).lower()
    rest = m.group(2).replace('\\\\', '/')
    print(f'/{drive}/{rest}')
else:
    print(p)
" "${transcript_path}" 2>/dev/null || echo "${transcript_path}")"
    fi

    printf '[%s] STOP learn-extract transcript="%s"\n' "$(iso_now)" \
        "${transcript_path}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true

    if [ -z "${transcript_path}" ] || [ ! -f "${transcript_path}" ]; then
        printf '[%s] STOP learn-extract exit: no transcript\n' "$(iso_now)" \
        >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
        return 0
    fi

    local _learn_session_id _learn_project_raw _learn_project
    _learn_session_id="$("${PYTHON}" -c "import os; print(os.getppid())" \
        2>/dev/null || echo "$$")"
    _learn_project_raw="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    _learn_project="$(to_native_path "${_learn_project_raw}" \
        2>/dev/null || echo "${_learn_project_raw}")"
    _learn_project="${_learn_project//\\//}"

    local learnings=""

    # --- LAYER 1: LLM extraction via saved claude path ---
    local _claude_bin=""
    local _bin_file="${CLAUDE_DIR}/memory/.claude-bin"

    if [ -f "${_bin_file}" ]; then
        _claude_bin="$(cat "${_bin_file}" 2>/dev/null | tr -d '[:space:]')"
    fi

    # Also try PATH as a secondary check (works on macOS/Linux)
    if [ -z "${_claude_bin}" ] || [ ! -x "${_claude_bin}" ]; then
        _claude_bin="$(command -v claude 2>/dev/null || true)"
    fi

    if [ -n "${_claude_bin}" ] && [ -x "${_claude_bin}" ]; then
        printf '[%s] STOP learn-extract using claude at %s\n' "$(iso_now)" \
            "${_claude_bin}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true

        local transcript_excerpt
        transcript_excerpt="$(tail -c 4000 "${transcript_path}" 2>/dev/null || true)"

        if [ -n "${transcript_excerpt}" ]; then
            local learn_prompt
            learn_prompt="Session transcript (last portion):
${transcript_excerpt}

---
Read this transcript excerpt. Extract up to 5 observations worth saving to
persistent memory across sessions.

Include ONLY items that match these criteria:
- Non-obvious bugs and their confirmed root cause
- APIs, tools, or libraries behaving unexpectedly or differently than documented
- Project-specific conventions discovered by reading code (not told explicitly)
- Commands, flags, or sequences that fixed a recurring or tricky error
- Architectural decisions and the reasoning behind them
- Platform-specific gotchas (Windows, macOS, version differences)
- Anything you would want to know at the start of the next session to avoid
  repeating a mistake or rediscovering something already solved

Output ONLY the observations, one per line, max 150 characters each, plain
text, no bullets, no numbering, no prefixes. If nothing qualifies, output
nothing."

            learnings="$(printf '%s' "${learn_prompt}" | \
                "${_claude_bin}" -p 2>/dev/null || true)"

            if [ -n "${learnings}" ]; then
                printf '[%s] STOP learn-extract LLM success\n' "$(iso_now)" \
                    >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
            else
                printf '[%s] STOP learn-extract LLM returned empty\n' "$(iso_now)" \
                    >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
            fi
        fi
    else
        printf '[%s] STOP learn-extract claude not found, using Python fallback\n' \
            "$(iso_now)" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    fi

    # --- LAYER 2: Python fallback if LLM extraction produced nothing ---
    # Reads JSONL transcript directly. Stores every assistant message
    # over 60 chars. No filtering - nothing suppressed. Some noise is fine.
    if [ -z "${learnings}" ]; then
        printf '[%s] STOP learn-extract running Python fallback\n' "$(iso_now)" \
            >> "${LOG_DIR}/sessions.log" 2>/dev/null || true

        learnings="$("${PYTHON}" - "${transcript_path}" <<'PYEOF' 2>/dev/null || echo ''
import sys, json, re

path = sys.argv[1]
try:
    with open(path, encoding='utf-8', errors='replace') as f:
        raw_lines = f.readlines()
except Exception:
    sys.exit(0)

messages = []
for line in reversed(raw_lines):
    line = line.strip()
    if not line:
        continue
    try:
        entry = json.loads(line)
    except Exception:
        continue
    if entry.get('role') != 'assistant':
        continue
    content = entry.get('content', '')
    if isinstance(content, list):
        text = ' '.join(
            c.get('text', '') for c in content
            if isinstance(c, dict) and c.get('type') == 'text'
        )
    elif isinstance(content, str):
        text = content
    else:
        continue
    text = text.strip()
    # Take only the first sentence
    first = re.split(r'(?<=[.!?])\s', text)[0].strip()
    first = re.sub(r'\s+', ' ', first)
    if len(first) >= 60:
        messages.append(first[:150])
    if len(messages) >= 5:
        break

for m in messages:
    print(m)
PYEOF
)"
    fi

    if [ -z "${learnings}" ]; then
        printf '[%s] STOP learn-extract: nothing to store\n' "$(iso_now)" \
            >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
        return 0
    fi

    # Store each learning in the DB
    local _stored=0
    printf '%s' "${learnings}" | while IFS= read -r _learn_line; do
        [ -z "${_learn_line}" ] && continue
        local _learn_tags
        _learn_tags="$("${PYTHON}" -c "
import sys, os
sys.path.insert(0, os.path.expanduser('~/.claude/scripts'))
try:
    from db import extract_keywords
    print(','.join(extract_keywords(sys.argv[1])))
except Exception:
    print('')
" "${_learn_line}" 2>/dev/null || echo '')"
        "${PYTHON}" "${DB_PY}" observe \
            "${_learn_session_id}" "${_learn_project}" \
            "${_learn_line}" "${_learn_tags}" 2>/dev/null && \
            _stored=$(( _stored + 1 )) || true
    done

    printf '[%s] STOP learning-extracted\n' "$(iso_now)" \
        >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
}

if [ -z "${test_cmd}" ]; then
    printf '[%s] STOP no-test-cmd found\n' "${iso}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true
    run_learning_extraction
    notify_session_end "Session ended — memory updated"
    exit 0
fi

test_output="$(cd "${git_root}" && bash -c "${test_cmd}" 2>&1)" && test_rc=0 || test_rc=$?

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

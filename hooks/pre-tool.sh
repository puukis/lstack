#!/usr/bin/env bash
# PreToolUse hook: loop detection, bash safety gates, tool logging

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"
LOG_DIR="${CLAUDE_DIR}/logs"
LOG_FILE="${LOG_DIR}/tool-calls.log"
STATE_FILE="${LOG_DIR}/loop-$$.json"

mkdir -p "${LOG_DIR}"

# Read stdin
input="$(cat)"

# Parse tool_name and tool_input via python3
parsed="$(printf '%s' "${input}" | "${PYTHON}" - <<'PYEOF'
import sys, json, hashlib, os

data = {}
try:
    data = json.loads(sys.stdin.read())
except Exception:
    pass

tool_name = data.get("tool_name", "")
tool_input = data.get("tool_input", {})

# Hash tool_name + tool_input for loop detection
raw = tool_name + ":" + json.dumps(tool_input, sort_keys=True)
h = hashlib.sha256(raw.encode()).hexdigest()[:16]

# Extract bash command if applicable
bash_cmd = ""
if tool_name == "Bash":
    bash_cmd = tool_input.get("command", "")

print(tool_name)
print(h)
print(bash_cmd)
PYEOF
)" 2>/dev/null || true

tool_name="$(printf '%s' "${parsed}" | sed -n '1p')"
input_hash="$(printf '%s' "${parsed}" | sed -n '2p')"
bash_cmd="$(printf '%s' "${parsed}" | sed -n '3p')"

# Fallback if python3 fails
if [ -z "${tool_name}" ]; then
    tool_name="unknown"
    input_hash="0000000000000000"
fi

# LOOP DETECTION
# State file stores last 20 {tool_name, hash} pairs as JSON array
if [ -f "${STATE_FILE}" ]; then
    loop_result="$("${PYTHON}" - <<PYEOF 2>/dev/null || echo "ok"
import json

state_file = "${STATE_FILE}"
tool_name = "${tool_name}"
input_hash = "${input_hash}"

try:
    with open(state_file) as f:
        entries = json.load(f)
except Exception:
    entries = []

# Append new entry
entries.append({"tool": tool_name, "hash": input_hash})
# Keep last 20
entries = entries[-20:]

# Write back
with open(state_file, "w") as f:
    json.dump(entries, f)

# Check last 3 for identical tool+hash
if len(entries) >= 3:
    last3 = entries[-3:]
    if all(e["tool"] == tool_name and e["hash"] == input_hash for e in last3):
        print("loop")
    else:
        print("ok")
else:
    print("ok")
PYEOF
)"
else
    # Create initial state file
    "${PYTHON}" -c "
import json
with open('${STATE_FILE}', 'w') as f:
    json.dump([{'tool': '${tool_name}', 'hash': '${input_hash}'}], f)
" 2>/dev/null || printf '[{"tool":"%s","hash":"%s"}]' "${tool_name}" "${input_hash}" > "${STATE_FILE}"
    loop_result="ok"
fi

if [ "${loop_result}" = "loop" ]; then
    printf 'Loop detected: %s called 3x with identical input. I will not retry. Tell me what to do differently.' "${tool_name}"
    exit 2
fi

# BASH SAFETY GATES
if [ "${tool_name}" = "Bash" ] && [ -n "${bash_cmd}" ]; then
    # Check each dangerous pattern
    if printf '%s' "${bash_cmd}" | grep -qE 'rm[[:space:]]+-rf[[:space:]]+[^-]'; then
        printf 'Blocked: rm -rf with target detected. Refusing destructive delete.'
        exit 2
    fi
    if printf '%s' "${bash_cmd}" | grep -qiE 'DROP[[:space:]]+TABLE'; then
        printf 'Blocked: DROP TABLE detected. Refusing destructive database operation.'
        exit 2
    fi
    if printf '%s' "${bash_cmd}" | grep -qE 'git[[:space:]]+push[[:space:]]+--force'; then
        printf 'Blocked: git push --force detected. Use --force-with-lease or confirm explicitly.'
        exit 2
    fi
    if printf '%s' "${bash_cmd}" | grep -qiE 'TRUNCATE[[:space:]]+TABLE|TRUNCATE[[:space:]]+[a-zA-Z]'; then
        printf 'Blocked: TRUNCATE detected. Refusing destructive database operation.'
        exit 2
    fi
    if printf '%s' "${bash_cmd}" | grep -qE ':\(\)\{:|:\(\){:'; then
        printf 'Blocked: fork bomb pattern detected.'
        exit 2
    fi
    if printf '%s' "${bash_cmd}" | grep -qE 'mkfs'; then
        printf 'Blocked: mkfs detected. Refusing filesystem format command.'
        exit 2
    fi
fi

# LOG
iso="$(iso_now)"
printf '[%s] %s %s\n' "${iso}" "${tool_name}" "${input_hash}" >> "${LOG_FILE}" 2>/dev/null || true

exit 0

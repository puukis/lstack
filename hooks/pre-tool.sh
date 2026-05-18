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

# --- mid-session memory lookup ---
if [ "${tool_name}" = "Read" ] || [ "${tool_name}" = "Bash" ]; then
    MEM_STATE_FILE="${LOG_DIR}/mem-${PPID}.json"

    # Increment call counter
    _mem_call_count="$("${PYTHON}" -c "
import json,sys
f=sys.argv[1]
try: d=json.load(open(f))
except: d={}
d['mem_call_count']=d.get('mem_call_count',0)+1
json.dump(d,open(f,'w'))
print(d['mem_call_count'])
" "${MEM_STATE_FILE}" 2>/dev/null || echo "0")"

    _mem_last_inject="$("${PYTHON}" -c "
import json,sys
try: d=json.load(open(sys.argv[1]))
except: d={}
print(d.get('mem_last_inject',-15))
" "${MEM_STATE_FILE}" 2>/dev/null || echo "-15")"

    _calls_since=$(( _mem_call_count - _mem_last_inject ))

    if [ "${_calls_since}" -ge 15 ]; then
        # Extract file path or command for dedup check
        _mem_file_path="$(printf '%s' "${input}" | "${PYTHON}" -c "
import sys,json
try:
  d=json.loads(sys.stdin.read())
  ti=d.get('tool_input',{})
  print((ti.get('file_path') or ti.get('command',''))[:80])
except: print('')
" 2>/dev/null || echo '')"

        _already_injected="$("${PYTHON}" -c "
import json,sys
try: d=json.load(open(sys.argv[1]))
except: d={}
files=d.get('mem_injected_files',[])
print('1' if sys.argv[2] in files else '0')
" "${MEM_STATE_FILE}" "${_mem_file_path}" 2>/dev/null || echo "0")"

        if [ "${_already_injected}" = "0" ]; then
            # Extract keywords from the tool input
            _mem_keywords="$("${PYTHON}" -c "
import sys,os,json
sys.path.insert(0,os.path.expanduser('~/.claude/scripts'))
try:
  from db import extract_keywords
  d=json.loads(sys.argv[1]) if sys.argv[1].startswith('{') else {}
  ti=d.get('tool_input',{})
  text=ti.get('file_path') or ti.get('command','')
  kws=extract_keywords(text)
  print(' '.join(kws))
except: print('')
" "${input}" 2>/dev/null || echo '')"

            if [ -n "${_mem_keywords}" ]; then
                _mem_project_raw="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
                _mem_project="$(to_native_path "${_mem_project_raw}" 2>/dev/null || echo "${_mem_project_raw}")"
                _mem_project="${_mem_project//\\//}"
                _mem_results="$("${PYTHON}" "${DB_PY}" search \
                    "${_mem_keywords}" --project "${_mem_project}" --limit 2 2>/dev/null || echo '[]')"

                _mem_count="$(printf '%s' "${_mem_results}" | "${PYTHON}" -c "
import sys,json
try: print(len(json.load(sys.stdin)))
except: print(0)
" 2>/dev/null || echo "0")"

                if [ "${_mem_count}" -gt 0 ]; then
                    _mem_inject_text="$(printf '%s' "${_mem_results}" | "${PYTHON}" -c "
import sys,json
try:
  items=json.load(sys.stdin)
  lines=[]
  for it in items:
    c=(it.get('content',''))[:150]
    d=(it.get('created_at',''))[:10]
    lines.append(f'[{d}] {c}')
  print('\n'.join(lines))
except: print('')
" 2>/dev/null || echo '')"

                    if [ -n "${_mem_inject_text}" ]; then
                        _mem_escaped="$("${PYTHON}" -c "import sys,json; print(json.dumps(sys.argv[1]))" "${_mem_inject_text}" 2>/dev/null)"
                        printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","additionalContext":%s}}\n' "${_mem_escaped}"

                        # Update state: record last inject count and file path
                        "${PYTHON}" -c "
import json,sys
f,count,fpath=sys.argv[1],int(sys.argv[2]),sys.argv[3]
try: d=json.load(open(f))
except: d={}
d['mem_last_inject']=count
files=d.get('mem_injected_files',[])
if fpath and fpath not in files: files.append(fpath)
d['mem_injected_files']=files[-20:]
json.dump(d,open(f,'w'))
" "${MEM_STATE_FILE}" "${_mem_call_count}" "${_mem_file_path}" 2>/dev/null || true
                    fi
                fi
            fi
        fi
    fi
fi
# --- end mid-session memory lookup ---

# CONTEXT PRUNER: warn when Read tool re-reads a file already in session context
if [ "${tool_name}" = "Read" ]; then
    read_path="$(printf '%s' "${input}" | "${PYTHON}" -c "
import sys, json, os
data = {}
try:
    data = json.loads(sys.stdin.read())
except Exception:
    pass
path = data.get('tool_input', {}).get('file_path', '')
if path:
    path = os.path.expanduser(path)
    try:
        path = os.path.abspath(path)
    except Exception:
        pass
print(path)
" 2>/dev/null || echo '')"

    if [ -n "${read_path}" ]; then
        READS_FILE="${LOG_DIR}/reads-${PPID}.json"
        already_read="$("${PYTHON}" - <<PYEOF 2>/dev/null || echo 'no'
import json
reads_file = "${READS_FILE}"
file_path = "${read_path}"
try:
    with open(reads_file) as f:
        state = json.load(f)
except Exception:
    state = {"reads": []}
if file_path in state.get("reads", []):
    print("yes")
else:
    reads = state.get("reads", [])
    reads.append(file_path)
    state["reads"] = reads
    with open(reads_file, "w") as f:
        json.dump(state, f)
    print("no")
PYEOF
)"
        if [ "${already_read}" = "yes" ]; then
            printf '{"additionalContext": "Note: %s was already read this session. Use your existing knowledge of this file unless you have a specific reason to re-read it."}\n' "${read_path}"
        fi
    fi
fi

# LOG
iso="$(iso_now)"
printf '[%s] %s %s\n' "${iso}" "${tool_name}" "${input_hash}" >> "${LOG_FILE}" 2>/dev/null || true

exit 0

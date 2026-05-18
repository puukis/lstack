#!/usr/bin/env bash
# PostToolUse hook: auto-format modified files + memory signal detector

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"
LOG_DIR="${CLAUDE_DIR}/logs"
LOG_FILE="${LOG_DIR}/tool-calls.log"
STATE_FILE="${HOME}/.claude/logs/loop-${CLAUDE_SESSION_ID:-$$}.json"

mkdir -p "${LOG_DIR}"

# Read stdin
INPUT="$(cat)"

# Extract tool name for routing
TOOL_NAME="$(printf '%s' "${INPUT}" | "${PYTHON}" -c "
import sys,json
try:
  d=json.load(sys.stdin)
  print(d.get('tool_name',''))
except: pass
" 2>/dev/null || true)"

# Extract file path via python3
file_path="$(printf '%s' "${INPUT}" | "${PYTHON}" - <<'PYEOF' 2>/dev/null || true
import sys, json

data = {}
try:
    data = json.loads(sys.stdin.read())
except Exception:
    pass

# PostToolUse: tool_response may contain file_path, or check tool_input
tool_input = data.get("tool_input", {})
file_path = (
    tool_input.get("file_path")
    or tool_input.get("path")
    or data.get("tool_response", {}).get("file_path")
    or ""
)
print(file_path)
PYEOF
)"

iso="$(iso_now)"

# Route: Bash tool calls skip formatter and fall through to signal detector.
# File-editing tools run the formatter and exit. Other tools exit cleanly.
if [ "${TOOL_NAME}" = "Bash" ]; then
    printf '[%s] post-tool bash-tool\n' "${iso}" >> "${LOG_FILE}" 2>/dev/null || true

    # CONTEXT PRUNER: warn when Bash response is large
    response_len="$(printf '%s' "${INPUT}" | "${PYTHON}" -c "
import sys,json
try:
  d=json.load(sys.stdin)
  r=d.get('tool_response',{})
  if isinstance(r,str): print(len(r))
  elif isinstance(r,dict): print(len(str(r.get('output',''))))
  else: print(0)
except: print(0)
" 2>/dev/null || echo '0')"

    if [ "${response_len}" -ge 3000 ] 2>/dev/null; then
        printf '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "Large tool response (%s chars). Extract only what you need — do not summarize the entire output back into context."}}\n' \
            "${response_len}"
    fi

    # fall through to signal detector below

elif [ -z "${file_path}" ] || [ ! -f "${file_path}" ]; then
    printf '[%s] post-tool no-file\n' "${iso}" >> "${LOG_FILE}" 2>/dev/null || true
    exit 0

else
    # Find project root (git root or file directory)
    project_root="$(git -C "$(dirname "${file_path}")" rev-parse --show-toplevel 2>/dev/null || dirname "${file_path}")"

    format_result=""
    formatter_used=""

    # Detect formatter by config file presence
    if ls "${project_root}"/.prettierrc* "${project_root}"/prettier.config.* 2>/dev/null | head -1 | grep -q .; then
        formatter_used="prettier"
        format_result="$(npx prettier --write "${file_path}" 2>&1)" && rc=0 || rc=$?
    elif [ -f "${project_root}/biome.json" ]; then
        formatter_used="biome"
        format_result="$(npx biome format --write "${file_path}" 2>&1)" && rc=0 || rc=$?
    elif [ -f "${project_root}/go.mod" ]; then
        formatter_used="gofmt"
        format_result="$(gofmt -w "${file_path}" 2>&1)" && rc=0 || rc=$?
    elif [ -f "${project_root}/Cargo.toml" ]; then
        formatter_used="rustfmt"
        format_result="$(rustfmt "${file_path}" 2>&1)" && rc=0 || rc=$?
    elif [ -f "${project_root}/.clang-format" ]; then
        formatter_used="clang-format"
        format_result="$(clang-format -i "${file_path}" 2>&1)" && rc=0 || rc=$?
    else
        printf '[%s] post-tool no-formatter %s\n' "${iso}" "${file_path}" >> "${LOG_FILE}" 2>/dev/null || true
        exit 0
    fi

    printf '[%s] post-tool %s %s\n' "${iso}" "${formatter_used}" "${file_path}" >> "${LOG_FILE}" 2>/dev/null || true

    if [ "${rc:-0}" -ne 0 ]; then
        escaped="$(printf '%s' "Formatter error (${formatter_used}): ${format_result}" | "${PYTHON}" -c "import sys,json; print(json.dumps(sys.stdin.read()))" 2>/dev/null || echo '"Formatter error"')"
        printf '{"additionalContext": %s}\n' "${escaped}"
    else
        escaped="$(printf '%s' "Auto-formatted ${file_path} with ${formatter_used}" | "${PYTHON}" -c "import sys,json; print(json.dumps(sys.stdin.read()))" 2>/dev/null || echo '"Auto-formatted"')"
        printf '{"additionalContext": %s}\n' "${escaped}"
    fi

    exit 0
fi

# --- memory signal detector ---
# Detect signals that suggest something worth remembering just happened.
# Does NOT save automatically — outputs additionalContext nudging Claude to /remember.
# Only fires on Bash tool (command results reveal the most learnable moments).

if [ "$TOOL_NAME" = "Bash" ]; then
  TOOL_RESPONSE=$(echo "$INPUT" | $PYTHON -c "
import sys,json
try:
  d=json.load(sys.stdin)
  r=d.get('tool_response',{})
  # tool_response may be string or object
  if isinstance(r,str): print(r[:500])
  elif isinstance(r,dict): print(str(r.get('output',''))[:500])
except: pass
" 2>/dev/null)

  TOOL_CMD=$(echo "$INPUT" | $PYTHON -c "
import sys,json
try:
  d=json.load(sys.stdin)
  print(d.get('tool_input',{}).get('command','')[:200])
except: pass
" 2>/dev/null)

  # Check for signals in the command + response
  SIGNAL=$($PYTHON -c "
import sys
cmd=sys.argv[1].lower()
resp=sys.argv[2].lower()

signals = []

# Fix confirmed after failure
if any(w in resp for w in ['passed','success','fixed','resolved','works now','all tests']):
  if any(w in cmd for w in ['test','fix','patch','debug']):
    signals.append('fix confirmed')

# Unexpected error pattern resolved
if any(w in resp for w in ['deprecated','not found','version','incompatible','breaking']):
  signals.append('version or compatibility issue')

# Long-running command that finally worked
if any(w in cmd for w in ['install','build','compile','migrate','init']):
  if '0' in resp or 'done' in resp or 'success' in resp:
    signals.append('setup or build success')

print(signals[0] if signals else '')
" "$TOOL_CMD" "$TOOL_RESPONSE" 2>/dev/null)

  if [ -n "$SIGNAL" ]; then
    # Rate limit: only nudge once per 20 tool calls max
    NUDGE_COUNT=$($PYTHON -c "
import json,sys
f=sys.argv[1]
try: d=json.load(open(f))
except: d={}
c=d.get('nudge_count',0)+1
last=d.get('nudge_last',0)
total=d.get('total_count',0)+1
d.update({'nudge_count':c,'total_count':total})
json.dump(d,open(f,'w'))
# print gap since last nudge
print(total-last)
" "$STATE_FILE" 2>/dev/null || echo "99")

    if [ "$NUDGE_COUNT" -ge 20 ]; then
      $PYTHON -c "
import json,sys
f=sys.argv[1]
try: d=json.load(open(f))
except: d={}
d['nudge_last']=d.get('total_count',0)
json.dump(d,open(f,'w'))
" "$STATE_FILE" 2>/dev/null

      SIGNAL_MSG="Signal detected: [$SIGNAL]. If this is reusable knowledge, call /remember with a specific one-sentence summary before continuing."

      printf '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "%s"}}\n' \
        "$(echo "$SIGNAL_MSG" | $PYTHON -c "import sys,json; print(json.dumps(sys.stdin.read())[1:-1])")"
    fi
  fi
fi
# --- end memory signal detector ---

exit 0

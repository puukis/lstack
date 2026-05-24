#!/usr/bin/env bash
# PostToolUse hook: auto-format modified files + LBrain capture

source "${HOME}/.claude/scripts/os.sh"

_run_lbrain_capture() {
    if [ -f "${HOME}/.claude/scripts/lbrain-capture-hook.py" ]; then
        printf '%s\n' "${INPUT}" | run_python "${HOME}/.claude/scripts/lbrain-capture-hook.py" post-tool 2>/dev/null || true
    fi
}

CLAUDE_DIR="${HOME}/.claude"
LOG_DIR="${CLAUDE_DIR}/logs"
LOG_FILE="${LOG_DIR}/tool-calls.log"

mkdir -p "${LOG_DIR}"

# Read stdin
INPUT="$(cat)"

# Extract tool name for routing
TOOL_NAME="$(printf '%s' "${INPUT}" | run_python -c '
import sys,json
try:
  d=json.load(sys.stdin)
  print(d.get("tool_name",""))
except: pass
' 2>/dev/null)" || TOOL_NAME=""

# Extract file path
file_path="$(printf '%s' "${INPUT}" | run_python -c '
import sys, json
data = {}
try:
    data = json.loads(sys.stdin.read())
except Exception:
    pass
tool_input = data.get("tool_input", {})
print(
    tool_input.get("file_path")
    or tool_input.get("path")
    or data.get("tool_response", {}).get("file_path")
    or ""
)
' 2>/dev/null)" || file_path=""

iso="$(iso_now)"

if [ "${TOOL_NAME}" = "Bash" ]; then
    printf '[%s] post-tool bash-tool\n' "${iso}" >> "${LOG_FILE}" 2>/dev/null || true

    # Warn when Bash response is large
    response_len="$(printf '%s' "${INPUT}" | run_python -c '
import sys,json
try:
  d=json.load(sys.stdin)
  r=d.get("tool_response",{})
  if isinstance(r,str): print(len(r))
  elif isinstance(r,dict): print(len(str(r.get("output",""))))
  else: print(0)
except: print(0)
' 2>/dev/null)" || response_len=0

    if [ "${response_len:-0}" -ge 3000 ] 2>/dev/null; then
        printf '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "Large tool response (%s chars). Extract only what you need — do not summarize the entire output back into context."}}\n' \
            "${response_len}"
    fi

    _run_lbrain_capture
    exit 0

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
        _run_lbrain_capture
        exit 0
    fi

    printf '[%s] post-tool %s %s\n' "${iso}" "${formatter_used}" "${file_path}" >> "${LOG_FILE}" 2>/dev/null || true

    if [ "${rc:-0}" -ne 0 ]; then
        escaped="$(printf '%s' "Formatter error (${formatter_used}): ${format_result}" | run_python -c 'import sys,json; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo '"Formatter error"')"
        printf '{"additionalContext": %s}\n' "${escaped}"
    else
        escaped="$(printf '%s' "Auto-formatted ${file_path} with ${formatter_used}" | run_python -c 'import sys,json; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo '"Auto-formatted"')"
        printf '{"additionalContext": %s}\n' "${escaped}"
    fi

    # Nudge /remember when editing a hook or script
    if printf '%s' "${file_path}" | grep -qE '/(hooks|scripts|skills)/'; then
        _edit_context="$(printf '%s' "${INPUT}" | run_python -c '
import sys,json
try:
  d=json.load(sys.stdin)
  ti=d.get("tool_input",{})
  old=str(ti.get("old_str",""))[:100]
  new=str(ti.get("new_str",""))[:100]
  if old and new:
      print(f"Changed: {old[:50]} -> {new[:50]}")
  else:
      print(ti.get("file_path",""))
except: print("")
' 2>/dev/null)" || _edit_context=""

        if [ -n "${_edit_context}" ]; then
            _edit_msg="You just edited a hook or script (${file_path##*/}). If you discovered a non-obvious bug or platform-specific behavior during this edit, call /remember."
            _edit_escaped="$(run_python -c 'import sys,json; print(json.dumps(sys.argv[1]))' "${_edit_msg}" 2>/dev/null)"
            printf '{"additionalContext": %s}\n' "${_edit_escaped}"
        fi
    fi

    _run_lbrain_capture
    exit 0
fi

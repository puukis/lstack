#!/usr/bin/env bash
# PostToolUse hook: auto-format modified files

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"
LOG_DIR="${CLAUDE_DIR}/logs"
LOG_FILE="${LOG_DIR}/tool-calls.log"

mkdir -p "${LOG_DIR}"

# Read stdin
input="$(cat)"

# Extract file path via python3
file_path="$(printf '%s' "${input}" | "${PYTHON}" - <<'PYEOF' 2>/dev/null || true
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

if [ -z "${file_path}" ] || [ ! -f "${file_path}" ]; then
    printf '[%s] post-tool no-file\n' "${iso}" >> "${LOG_FILE}" 2>/dev/null || true
    exit 0
fi

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

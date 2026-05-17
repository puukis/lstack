#!/usr/bin/env bash
# SessionStart hook: load memory context, log session

set -euo pipefail

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"
LOG_DIR="${CLAUDE_DIR}/logs"
GLOBAL_MEMORY="${CLAUDE_DIR}/memory/MEMORY.md"

mkdir -p "${LOG_DIR}"

# Collect memory content
memory_content=""

if [ -f "${GLOBAL_MEMORY}" ]; then
    memory_content="$(cat "${GLOBAL_MEMORY}" 2>/dev/null || true)"
fi

# Check for project-level memory at git root
git_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "${git_root}" ] && [ -f "${git_root}/.claude/memory/MEMORY.md" ]; then
    project_mem="$(cat "${git_root}/.claude/memory/MEMORY.md" 2>/dev/null || true)"
    if [ -n "${project_mem}" ]; then
        memory_content="${memory_content}

--- PROJECT MEMORY (${git_root}) ---
${project_mem}"
    fi
fi

# Output additionalContext if we have content
if [ -n "${memory_content}" ]; then
    # Escape for JSON
    escaped="$(printf '%s' "${memory_content}" | "${PYTHON}" -c "
import sys, json
content = sys.stdin.read()
print(json.dumps(content))
" 2>/dev/null || echo '""')"
    printf '{"additionalContext": %s}\n' "${escaped}"
fi

# Log session start
iso="$(iso_now)"
cwd="$(pwd 2>/dev/null || echo 'unknown')"
printf '[%s] SESSION_START cwd=%s\n' "${iso}" "${cwd}" >> "${LOG_DIR}/sessions.log" 2>/dev/null || true

exit 0

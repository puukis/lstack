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

# GIT-AWARE CONTEXT: inject compact git state (token cap: ~200 tokens)
git_context=""
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
    git_branch="$(git branch --show-current 2>/dev/null || true)"
    git_last="$(git log -1 --pretty="%s" 2>/dev/null || true)"
    git_stat="$(git diff --stat HEAD 2>/dev/null | head -10 || true)"
    git_stash="$(git stash list 2>/dev/null | wc -l | tr -d ' ' || echo 0)"

    if [ -n "${git_branch}" ] || [ -n "${git_last}" ] || [ -n "${git_stat}" ]; then
        git_context="--- git context ---
branch: ${git_branch:-unknown}
last commit: ${git_last:-none}"
        if [ -n "${git_stat}" ]; then
            git_context="${git_context}
changed:
${git_stat}"
        fi
        if [ "${git_stash}" -gt 0 ] 2>/dev/null; then
            git_context="${git_context}
stashes: ${git_stash}"
        fi
    fi
fi

if [ -n "${git_context}" ]; then
    if [ -n "${memory_content}" ]; then
        memory_content="${memory_content}

${git_context}"
    else
        memory_content="${git_context}"
    fi
fi

# --- lstack persistent memory --- (db.py session-start)
SESSION_ID="${CLAUDE_SESSION_ID:-$(${PYTHON} -c "import os; print(os.getppid())" 2>/dev/null || echo "$$")}"
_db_project="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
_db_project="$(realpath "${_db_project}" 2>/dev/null || echo "${_db_project}")"

_db_result="$(${PYTHON} "${HOME}/.claude/scripts/db.py" session-start "${SESSION_ID}" "${_db_project}" 2>/dev/null || true)"
_db_context="$(printf '%s' "${_db_result}" | ${PYTHON} -c "
import sys,json
try:
  d=json.load(sys.stdin)
  print(d.get('context',''))
except: pass
" 2>/dev/null || true)"

if [ -n "${_db_context}" ]; then
    _db_block="--- persistent memory (past sessions) ---
${_db_context}
--- end persistent memory ---"
    if [ -n "${memory_content}" ]; then
        memory_content="${memory_content}

${_db_block}"
    else
        memory_content="${_db_block}"
    fi
fi
# --- end lstack persistent memory ---

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

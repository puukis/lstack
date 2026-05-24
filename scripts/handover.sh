#!/usr/bin/env bash
# Standalone handover generator — run manually to capture current session state

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"

usage() {
    echo "Usage: handover.sh [transcript_path]"
    echo "Generates a handover summary from a Claude transcript."
    echo "If transcript_path is omitted, looks for most recent session."
    exit 1
}

transcript_path="${1:-}"

if [ -z "${transcript_path}" ]; then
    # Try to find the most recent session transcript
    sessions_dir="${CLAUDE_DIR}/projects"
    transcript_path="$(find "${sessions_dir}" -name "*.jsonl" 2>/dev/null | sort -t_ -k2 -n | tail -1 || true)"
fi

if [ -z "${transcript_path}" ] || [ ! -f "${transcript_path}" ]; then
    echo "No transcript found. Pass a path explicitly."
    usage
fi

git_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "${git_root}" ]; then
    out_dir="${git_root}/.claude/memory"
    mkdir -p "${out_dir}"
    out_path="${out_dir}/handover.md"
else
    out_path="${CLAUDE_DIR}/memory/handover.md"
fi

echo "Generating handover from: ${transcript_path}"
echo "Output: ${out_path}"

if [ -n "${LSTACK_INSIDE_HOOK:-}" ]; then
    echo "Skipped: LSTACK_INSIDE_HOOK is set."
    exit 0
fi

claude -p --allowedTools "" \
    "Read ${transcript_path}. Write a handover summary (max 300 words, plain text, no headers):
1. Current task and exact status
2. What was tried, what worked, what failed
3. Key decisions and why
4. Exact next step
Be specific. No padding." > "${out_path}" 2>/dev/null && \
    echo "Handover saved to ${out_path}" || \
    echo "Failed to generate handover (claude command unavailable?)"

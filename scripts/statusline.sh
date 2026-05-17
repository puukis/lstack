#!/usr/bin/env bash
# Status line script: render a single-line status bar for Claude Code

source "${HOME}/.claude/scripts/os.sh"

command -v jq >/dev/null 2>&1 || { printf ' lstack'; exit 0; }

input="$(cat)"

model="$(printf '%s' "${input}" | jq -r '.model.display_name // "claude"' 2>/dev/null || echo 'claude')"
cost="$(printf '%s' "${input}" | jq -r '.cost.total_cost_usd // 0' 2>/dev/null || echo '0')"
pct="$(printf '%s' "${input}" | jq -r '.context_window.used_percentage // 0' 2>/dev/null || echo '0')"
branch="$(printf '%s' "${input}" | jq -r '.workspace.git_worktree // ""' 2>/dev/null || echo '')"
added="$(printf '%s' "${input}" | jq -r '.cost.total_lines_added // 0' 2>/dev/null || echo '0')"
removed="$(printf '%s' "${input}" | jq -r '.cost.total_lines_removed // 0' 2>/dev/null || echo '0')"

# Format cost to 3 decimal places
cost_fmt="$("${PYTHON}" -c "print(f'{float(\"${cost}\"):.3f}')" 2>/dev/null || printf '%.3f' "${cost}")"

# Integer percentage
pct_int="${pct%%.*}"
pct_int="${pct_int:-0}"

# Windows fallback — plain text, no ANSI
if [ "$OS" = "windows" ]; then
    printf ' %s | %s%% | $%s\n' "${model}" "${pct_int}" "${cost_fmt}"
    exit 0
fi

# ANSI codes
RESET='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'

# Build 10-char context bar
bar=""
filled=$(( pct_int * 10 / 100 ))
[ "${filled}" -gt 10 ] && filled=10
empty=$(( 10 - filled ))

i=0
while [ "${i}" -lt "${filled}" ]; do
    bar="${bar}█"
    i=$(( i + 1 ))
done
i=0
while [ "${i}" -lt "${empty}" ]; do
    bar="${bar}░"
    i=$(( i + 1 ))
done

# Bar color based on percentage
if [ "${pct_int}" -ge 80 ] 2>/dev/null; then
    bar_color="${RED}"
elif [ "${pct_int}" -ge 60 ] 2>/dev/null; then
    bar_color="${YELLOW}"
else
    bar_color="${GREEN}"
fi

# Build output line
line="${BOLD}${model}${RESET}"

if [ -n "${branch}" ]; then
    line="${line} on ${branch}"
fi

line="${line}  ${bar_color}${bar}${RESET} ${pct_int}%  ${DIM}\$${cost_fmt}  +${added} -${removed}${RESET}"

printf '%b\n' "${line}"
exit 0

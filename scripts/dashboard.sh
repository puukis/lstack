#!/usr/bin/env bash
# lstack dashboard — live display of parallel agent worktrees

source "${HOME}/.claude/scripts/os.sh"

CLAUDE_DIR="${HOME}/.claude"
PARALLEL_DIR="${CLAUDE_DIR}/parallel"

# Compute age in seconds from directory mtime
age_seconds() {
    local dir="$1"
    local now mtime
    now="$("${PYTHON}" -c "import time; print(int(time.time()))" 2>/dev/null || echo 0)"
    mtime="$(file_mtime "${dir}" 2>/dev/null || echo "${now}")"
    echo $(( now - mtime ))
}

format_age() {
    local secs="$1"
    printf '%d:%02d' $(( secs / 60 )) $(( secs % 60 ))
}

agent_status() {
    local result="${1}/result.md"
    if [ ! -f "${result}" ]; then
        echo "running"
        return
    fi
    local last
    last="$(tail -1 "${result}" 2>/dev/null | tr '[:lower:]' '[:upper:]')"
    case "${last}" in
        *DONE*)   echo "done" ;;
        *ERROR*|*FAILED*) echo "failed" ;;
        *) echo "unknown" ;;
    esac
}

print_table() {
    local ts active=0 done_n=0 failed_n=0
    ts="$(iso_now 2>/dev/null || date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo 'unknown')"

    printf 'lstack dashboard — %s\n' "${ts}"
    printf '%s\n' '─────────────────────────────────────────────────────────'
    printf '%-32s %-22s %-10s %s\n' 'WORKTREE' 'BRANCH' 'STATUS' 'AGE'

    if [ -d "${PARALLEL_DIR}" ]; then
        for worktree in "${PARALLEL_DIR}"/agent-*; do
            [ -d "${worktree}" ] || continue
            local wname branch status age_s age_fmt
            wname="${worktree#${CLAUDE_DIR}/}"
            branch="$(git -C "${worktree}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
            status="$(agent_status "${worktree}")"
            age_s="$(age_seconds "${worktree}")"
            age_fmt="$(format_age "${age_s}")"
            printf '%-32s %-22s %-10s %s\n' "${wname}" "${branch}" "${status}" "${age_fmt}"
            case "${status}" in
                running) active=$(( active + 1 )) ;;
                done)    done_n=$(( done_n + 1 )) ;;
                failed)  failed_n=$(( failed_n + 1 )) ;;
            esac
        done
    fi

    printf '%s\n' '─────────────────────────────────────────────────────────'
    printf 'active: %d   done: %d   failed: %d\n' "${active}" "${done_n}" "${failed_n}"
    printf '%s\n' '─────────────────────────────────────────────────────────'
    printf 'logs: %s/logs/   [q] quit\n' "${CLAUDE_DIR}"
}

# Choose display mode based on OS and tput availability
if [ "${OS}" = "windows" ] || ! command -v tput >/dev/null 2>&1; then
    # Plain text loop — no cursor control
    while true; do
        clear 2>/dev/null || printf '\033[2J\033[H'
        print_table
        # Non-blocking read with 2s timeout; exit on 'q'
        if read -t 2 -n 1 key 2>/dev/null; then
            [ "${key}" = "q" ] && exit 0
        fi
    done
else
    # tput-based loop with cursor repositioning
    tput civis 2>/dev/null || true
    trap 'tput cnorm 2>/dev/null; exit 0' INT TERM EXIT
    tput clear 2>/dev/null || printf '\033[2J\033[H'
    while true; do
        tput cup 0 0 2>/dev/null || printf '\033[H'
        print_table
        if read -t 2 -n 1 key 2>/dev/null; then
            [ "${key}" = "q" ] && { tput cnorm 2>/dev/null; exit 0; }
        fi
    done
fi

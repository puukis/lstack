#!/usr/bin/env bash
# lstack installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/puukis/lstack/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/puukis/lstack/main/install.sh | bash -s -- --yes  # non-interactive
#   bash /path/to/lstack/install.sh

set -euo pipefail

LSTACK_REPO="https://github.com/puukis/lstack"
CLAUDE_DIR="${HOME}/.claude"
_INSTALL_START="$(date +%s 2>/dev/null || echo 0)"

# ─── Flags ────────────────────────────────────────────────────────────────────

INTERACTIVE=true
if [ "${1:-}" = "--yes" ] || [ "${1:-}" = "-y" ]; then
    INTERACTIVE=false
fi

_is_stdin_tty()  { [ -t 0 ]; }
_is_stdout_tty() { [ -t 1 ]; }

_skip_confirmation() {
    [ "${INTERACTIVE}" = false ] || ! _is_stdin_tty
}

# ─── Color palette (degrades gracefully when not a TTY) ───────────────────────

if _is_stdout_tty; then
    BOLD='\033[1m';    DIM='\033[2m';     RESET='\033[0m'
    GREEN='\033[32m';  YELLOW='\033[33m'; RED='\033[31m'
    CYAN='\033[36m';   BLUE='\033[34m';   WHITE='\033[97m'
else
    BOLD=''; DIM=''; RESET=''; GREEN=''; YELLOW=''; RED=''
    CYAN=''; BLUE=''; WHITE=''
fi

# ─── Script-dir detection ─────────────────────────────────────────────────────

_realpath() {
    if command -v realpath >/dev/null 2>&1; then
        realpath "$1"
    elif [ -d "$1" ]; then
        (cd "$1" && pwd)
    else
        (cd "$(dirname "$1")" && printf '%s/%s\n' "$(pwd)" "$(basename "$1")")
    fi
}

_detect_script_dir() {
    if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
        dirname "$(_realpath "${BASH_SOURCE[0]}")"
    elif [ -n "${0:-}" ] && [ -f "${0}" ]; then
        dirname "$(_realpath "${0}")"
    else
        printf '%s\n' "${PWD}"
    fi
}

SCRIPT_DIR="$(_detect_script_dir)"
IS_LOCAL_REPO=false
if [ -f "${SCRIPT_DIR}/bin/lstack" ] && [ -f "${SCRIPT_DIR}/scripts/gen-settings.sh" ]; then
    IS_LOCAL_REPO=true
fi

# ─── Logging helpers ──────────────────────────────────────────────────────────

TOTAL_STEPS=8
_current_step=0

_step() {
    _current_step=$(( _current_step + 1 ))
    printf '\n'
    printf "  ${DIM}──────────────────────────────────────────────────────────${RESET}\n"
    printf "  ${BOLD}${CYAN}[%d/%d]${RESET}  ${BOLD}%s${RESET}\n" "${_current_step}" "${TOTAL_STEPS}" "$1"
    printf "  ${DIM}──────────────────────────────────────────────────────────${RESET}\n"
    printf '\n'
}

_info()    { printf "  ${BLUE}→${RESET}  %s\n" "$1"; }
_ok()      { printf "  ${GREEN}✓${RESET}  %s\n" "$1"; }
_warn()    { printf "  ${YELLOW}⚠${RESET}  ${YELLOW}%s${RESET}\n" "$1"; }
_die()     {
    spin_stop
    printf '\n'
    printf "  ${RED}${BOLD}✗  Error:${RESET}  %s\n\n" "$1" >&2
    exit 1
}

check_pass() { printf "  ${GREEN}✓${RESET}  %-44s ${DIM}OK${RESET}\n" "$1"; }
check_fail() { printf "  ${RED}✗${RESET}  %-44s ${RED}FAIL${RESET}\n" "$1"; }
check_warn() { printf "  ${YELLOW}⚠${RESET}  %-44s ${YELLOW}WARN${RESET}\n" "$1"; }

# ─── Spinner ──────────────────────────────────────────────────────────────────

_spin_pid=''

_do_spin() {
    local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local msg="$1"
    local i=0
    # Hide cursor while spinning
    tput civis 2>/dev/null || true
    while true; do
        printf "\r  ${CYAN}${frames[$((i % 10))]}${RESET}  %s  " "${msg}"
        i=$(( i + 1 ))
        sleep 0.1
    done
}

spin_start() {
    if _is_stdout_tty; then
        _do_spin "$1" &
        _spin_pid=$!
    else
        _info "$1"
    fi
}

spin_stop() {
    if [ -n "${_spin_pid}" ]; then
        kill "${_spin_pid}" 2>/dev/null || true
        wait "${_spin_pid}" 2>/dev/null || true
        _spin_pid=''
        printf '\r\033[K'
        tput cnorm 2>/dev/null || true
    fi
}

# Always restore cursor and stop spinner on exit
trap 'spin_stop' EXIT INT TERM

# ─── Elapsed time helper ──────────────────────────────────────────────────────

_elapsed() {
    local now
    now="$(date +%s 2>/dev/null || echo 0)"
    local secs=$(( now - _INSTALL_START ))
    if [ "${secs}" -lt 60 ]; then
        printf '%ds' "${secs}"
    else
        printf '%dm %ds' "$(( secs / 60 ))" "$(( secs % 60 ))"
    fi
}

# ─── Banner ───────────────────────────────────────────────────────────────────

print_banner() {
    # Inner width = 58 visible chars between │ │
    printf '\n'
    printf "  ${DIM}┌──────────────────────────────────────────────────────────┐${RESET}\n"
    printf "  ${DIM}│${RESET}                                                          ${DIM}│${RESET}\n"
    printf "  ${DIM}│${RESET}   ${BOLD}${WHITE}lstack${RESET}  ·  Claude Code Engineering Environment         ${DIM}│${RESET}\n"
    printf "  ${DIM}│${RESET}   ${DIM}https://github.com/puukis/lstack${RESET}                       ${DIM}│${RESET}\n"
    printf "  ${DIM}│${RESET}                                                          ${DIM}│${RESET}\n"
    printf "  ${DIM}└──────────────────────────────────────────────────────────┘${RESET}\n"
    printf '\n'
}

# ─── Step 0: Banner + scope summary ──────────────────────────────────────────

print_banner

printf "  Installing into ${BOLD}%s${RESET}\n" "${CLAUDE_DIR}"
printf '\n'
printf "  ${DIM}What lstack touches:${RESET}\n"
printf "  ${DIM}  ~/.claude/CLAUDE.md          global Claude Code instructions${RESET}\n"
printf "  ${DIM}  ~/.claude/settings.json      hooks, spinner, statusline${RESET}\n"
printf "  ${DIM}  ~/.claude/hooks/             lifecycle hook scripts${RESET}\n"
printf "  ${DIM}  ~/.claude/scripts/           helper scripts${RESET}\n"
printf "  ${DIM}  ~/.claude/skills/            on-demand skill prompts${RESET}\n"
printf "  ${DIM}  ~/.claude/bin/lstack         CLI tool${RESET}\n"
printf "  ${DIM}  ~/.claude/memory/            memory index files${RESET}\n"
printf '\n'
printf "  ${DIM}What lstack never touches:${RESET}\n"
printf "  ${DIM}  ~/.claude/memory/preferences.md   your personal preferences${RESET}\n"
printf "  ${DIM}  ~/.claude/memory/patterns.md      your learned patterns${RESET}\n"
printf "  ${DIM}  ~/.claude/memory/lstack.db        your persistent memory DB${RESET}\n"
printf "  ${DIM}  Any project .claude/ directories${RESET}\n"
printf '\n'

if ! _skip_confirmation; then
    printf "  Press ${BOLD}Enter${RESET} to continue or ${BOLD}Ctrl+C${RESET} to abort. "
    read -r _confirm
    printf '\n'
else
    _info "Non-interactive mode — skipping confirmation."
fi

# ─── Step 1: Prerequisites ────────────────────────────────────────────────────

_step "Checking prerequisites"

_prereq_failures=0

if command -v git >/dev/null 2>&1; then
    _git_ver="$(git --version 2>/dev/null | awk '{print $3}')"
    check_pass "git (${_git_ver})"
else
    check_fail "git not found — install git and re-run"
    _prereq_failures=$(( _prereq_failures + 1 ))
fi

_py_path="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
if [ -n "${_py_path}" ]; then
    _py_ver="$("${_py_path}" --version 2>&1 | awk '{print $2}')"
    check_pass "python (${_py_ver})"
else
    check_warn "python3 not found — DB init will be skipped"
fi

if command -v bash >/dev/null 2>&1; then
    _bash_ver="$(bash --version 2>/dev/null | head -1 | sed 's/.*version //' | sed 's/ .*//')"
    check_pass "bash (${_bash_ver})"
fi

if [ "${_prereq_failures}" -gt 0 ]; then
    _die "Missing required tools. Install them and re-run the installer."
fi

# ─── Step 2: Detect existing ~/.claude ────────────────────────────────────────

_step "Checking for existing installation"

BACKUP_DIR=''

if [ -d "${CLAUDE_DIR}" ]; then
    if [ -f "${CLAUDE_DIR}/.git-source" ]; then
        _ok "Existing lstack install detected — running upgrade instead."
        printf '\n'
        spin_start "Pulling latest changes from origin/main..."
        if git -C "${CLAUDE_DIR}" pull --ff-only origin main 2>/dev/null; then
            spin_stop
            _ok "Upgrade complete."
        else
            spin_stop
            _warn "Fast-forward failed — local changes detected."
            _info "To upgrade manually:"
            _info "  git -C ~/.claude fetch origin"
            _info "  git -C ~/.claude reset --hard origin/main"
        fi
        printf '\n'
        printf "  ${DIM}Restart Claude Code to apply changes.${RESET}\n"
        printf '\n'
        exit 0
    else
        _warn "~/.claude already exists and was not installed by lstack."
        BACKUP_DIR="${HOME}/.claude.backup.$(date +%Y%m%d_%H%M%S)"
        _info "Backup destination: ${BACKUP_DIR}"
        printf '\n'
        if ! _skip_confirmation; then
            printf "  Continue and create backup? [${BOLD}y${RESET}/N] "
            read -r _answer
            case "${_answer}" in
                [yY]|[yY][eE][sS]) ;;
                *) printf '\n  Aborted.\n\n'; exit 0 ;;
            esac
            printf '\n'
        fi
        spin_start "Creating backup..."
        cp -r "${CLAUDE_DIR}" "${BACKUP_DIR}"
        spin_stop
        _ok "Backup created at ${BACKUP_DIR}"
    fi
else
    _ok "No existing ~/.claude found — clean install."
fi

# ─── Step 3: Install files ────────────────────────────────────────────────────

_step "Installing lstack files"

if [ "${IS_LOCAL_REPO}" = true ]; then
    _info "Source: local repo at ${SCRIPT_DIR}"
    spin_start "Copying files..."
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --exclude='.git' "${SCRIPT_DIR}/" "${CLAUDE_DIR}/"
    else
        mkdir -p "${CLAUDE_DIR}"
        cp -r "${SCRIPT_DIR}/." "${CLAUDE_DIR}/"
        rm -rf "${CLAUDE_DIR}/.git" 2>/dev/null || true
    fi
    spin_stop
    _ok "Files copied from local repo."
else
    _info "Source: ${LSTACK_REPO}"
    spin_start "Cloning repository..."
    git clone --quiet "${LSTACK_REPO}" "${CLAUDE_DIR}"
    spin_stop
    _ok "Repository cloned."
fi

# ─── Step 4: Permissions + settings ──────────────────────────────────────────

_step "Configuring permissions and settings"

spin_start "Setting executable permissions..."
chmod +x "${CLAUDE_DIR}/hooks/"*.sh   2>/dev/null || true
chmod +x "${CLAUDE_DIR}/scripts/"*.sh 2>/dev/null || true
chmod +x "${CLAUDE_DIR}/bin/lstack"   2>/dev/null || true
spin_stop
_ok "Executable bits set."

_OS="$(uname -s 2>/dev/null || echo 'Unknown')"
case "${_OS}" in
    Darwin)              _OS_NAME="macOS" ;;
    Linux)               _OS_NAME="Linux" ;;
    MINGW*|MSYS*|CYGWIN*) _OS_NAME="Windows (Git Bash)" ;;
    *)                   _OS_NAME="${_OS}" ;;
esac

spin_start "Generating settings.json for ${_OS_NAME}..."
bash "${CLAUDE_DIR}/scripts/gen-settings.sh" > "${CLAUDE_DIR}/settings.json"
spin_stop

if python3 -m json.tool "${CLAUDE_DIR}/settings.json" > /dev/null 2>&1; then
    _ok "settings.json generated and validated (${_OS_NAME})."
else
    _die "settings.json failed JSON validation — check gen-settings.sh output."
fi

# ─── Step 5: Git repo (enables lstack upgrade) ────────────────────────────────

_step "Initializing version tracking"

if [ ! -d "${CLAUDE_DIR}/.git" ]; then
    spin_start "Initializing git repo in ~/.claude..."
    git -C "${CLAUDE_DIR}" init -b main 2>/dev/null || git -C "${CLAUDE_DIR}" init
    git -C "${CLAUDE_DIR}" remote add origin "${LSTACK_REPO}" 2>/dev/null || true
    git -C "${CLAUDE_DIR}" add -A
    git -C "${CLAUDE_DIR}" commit -m "lstack install" --quiet 2>/dev/null || true
    spin_stop
    _ok "Git repo initialized in ~/.claude."
else
    _ok "Git repo already present."
fi

# Mark as lstack-managed
printf '%s\n' "${LSTACK_REPO}" > "${CLAUDE_DIR}/.git-source"

# ─── Step 6: Memory scaffolding ───────────────────────────────────────────────

_step "Creating memory scaffolding"

mkdir -p "${CLAUDE_DIR}/memory" "${CLAUDE_DIR}/logs"

if [ ! -f "${CLAUDE_DIR}/memory/MEMORY.md" ]; then
    if [ -f "${CLAUDE_DIR}/memory/MEMORY.md.template" ]; then
        cp "${CLAUDE_DIR}/memory/MEMORY.md.template" "${CLAUDE_DIR}/memory/MEMORY.md"
        _ok "MEMORY.md created from template."
    else
        cat > "${CLAUDE_DIR}/memory/MEMORY.md" <<'MEMEOF'
# lstack global memory index
# First 200 lines auto-loaded every session. Keep lean.

## Preferences
See preferences.md

## Patterns
See patterns.md

## Projects
See projects.md

## Last handover
See handover.md (auto-generated by PreCompact hook)
MEMEOF
        _ok "MEMORY.md initialized."
    fi
else
    _ok "MEMORY.md already exists — not overwritten."
fi

_scaffold_file() {
    local path="$1"; local label="$2"; local content="$3"
    if [ ! -f "${path}" ]; then
        printf '%s' "${content}" > "${path}"
        _ok "${label} created."
    else
        _ok "${label} already exists — not overwritten."
    fi
}

_scaffold_file "${CLAUDE_DIR}/memory/preferences.md" "preferences.md" \
'# Preferences
<!-- Your personal preferences. Claude updates this as it learns about you. -->
<!-- Name, primary languages, verbosity, workflow style, etc. -->
'

_scaffold_file "${CLAUDE_DIR}/memory/patterns.md" "patterns.md" \
'# Patterns
<!-- Coding and workflow patterns Claude has observed in your work. -->

## Architecture patterns

## Testing patterns

## Workflow patterns
'

_scaffold_file "${CLAUDE_DIR}/memory/projects.md" "projects.md" \
'# Projects
<!-- Active projects and their context. -->
'

# ─── Step 7: Persistent DB ────────────────────────────────────────────────────

_step "Initializing persistent memory database"

if [ -n "${_py_path}" ]; then
    spin_start "Initializing lstack.db..."
    "${_py_path}" "${CLAUDE_DIR}/scripts/db.py" init 2>/dev/null || true
    spin_stop
    _ok "Persistent DB initialized at ~/.claude/memory/lstack.db"
else
    _warn "python3 not found — DB init skipped."
    _warn "Install Python 3, then run: python3 ~/.claude/scripts/db.py init"
fi

# ─── Run onboarding ───────────────────────────────────────────────────────────

printf '\n'
bash "${CLAUDE_DIR}/bin/lstack" onboard

# ─── Step 8: Post-install verification ────────────────────────────────────────

_step "Verifying installation"

_failures=0

# Hook scripts executable
_hooks_ok=true
for _h in "${CLAUDE_DIR}/hooks/"*.sh; do
    [ -f "${_h}" ] || continue
    if [ ! -x "${_h}" ]; then _hooks_ok=false; break; fi
done
if "${_hooks_ok}" && ls "${CLAUDE_DIR}/hooks/"*.sh >/dev/null 2>&1; then
    check_pass "Hook scripts executable"
else
    check_fail "Hook scripts not executable"
    _info "Fix: chmod +x ~/.claude/hooks/*.sh"
    _failures=$(( _failures + 1 ))
fi

# settings.json valid
if python3 -m json.tool "${CLAUDE_DIR}/settings.json" >/dev/null 2>&1; then
    check_pass "settings.json valid JSON"
else
    check_fail "settings.json invalid"
    _info "Fix: lstack settings"
    _failures=$(( _failures + 1 ))
fi

# Python
if [ -n "${_py_path}" ]; then
    check_pass "Python 3 available"
else
    check_warn "Python 3 not found"
fi

# DB accessible
if [ -n "${_py_path}" ] && "${_py_path}" "${CLAUDE_DIR}/scripts/db.py" stats >/dev/null 2>&1; then
    check_pass "Persistent DB accessible"
else
    check_fail "Persistent DB not accessible"
    _info "Fix: python3 ~/.claude/scripts/db.py init"
    _failures=$(( _failures + 1 ))
fi

# lstack CLI
if bash "${CLAUDE_DIR}/bin/lstack" help >/dev/null 2>&1; then
    check_pass "lstack CLI works"
else
    check_fail "lstack CLI failed"
    _info "Fix: chmod +x ~/.claude/bin/lstack"
    _failures=$(( _failures + 1 ))
fi

# ─── Final summary ────────────────────────────────────────────────────────────

_elapsed_str="$(_elapsed)"

printf '\n'

if [ "${_failures}" -eq 0 ]; then
    # Inner width = 58 visible chars between │ │
    printf "  ${DIM}┌──────────────────────────────────────────────────────────┐${RESET}\n"
    printf "  ${DIM}│${RESET}                                                          ${DIM}│${RESET}\n"
    printf "  ${DIM}│${RESET}   ${BOLD}${GREEN}✓  lstack installed successfully${RESET}                       ${DIM}│${RESET}\n"
    printf "  ${DIM}│${RESET}                                                          ${DIM}│${RESET}\n"
    printf "  ${DIM}│${RESET}   ${BOLD}Next steps:${RESET}                                            ${DIM}│${RESET}\n"
    printf "  ${DIM}│${RESET}   ${CYAN}1.${RESET} Restart Claude Code                                 ${DIM}│${RESET}\n"
    printf "  ${DIM}│${RESET}   ${CYAN}2.${RESET} Open any project and run: ${BOLD}lstack init${RESET}               ${DIM}│${RESET}\n"
    printf "  ${DIM}│${RESET}   ${CYAN}3.${RESET} Check status anytime: ${BOLD}lstack status${RESET}                 ${DIM}│${RESET}\n"
    printf "  ${DIM}│${RESET}                                                          ${DIM}│${RESET}\n"
    printf "  ${DIM}└──────────────────────────────────────────────────────────┘${RESET}\n"
    printf '\n'
    printf "  ${DIM}Completed in %s${RESET}\n" "${_elapsed_str}"
    printf '\n'
else
    printf "  ${YELLOW}${BOLD}%d check(s) failed.${RESET}  Fix the issues above, then restart Claude Code.\n" "${_failures}"
    printf "  Run ${BOLD}lstack doctor${RESET} anytime to re-check.\n"
    printf '\n'
    exit 1
fi

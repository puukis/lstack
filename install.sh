#!/usr/bin/env bash
# lstack installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/puukis/lstack/main/install.sh | bash
#   bash /path/to/lstack/install.sh

set -euo pipefail

LSTACK_REPO="https://github.com/puukis/lstack"
CLAUDE_DIR="${HOME}/.claude"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

print_banner() {
    printf '\n'
    printf '╔══════════════════════════════════════════════════════════╗\n'
    printf '║                    lstack installer                      ║\n'
    printf '║         github.com/puukis/lstack                        ║\n'
    printf '╚══════════════════════════════════════════════════════════╝\n'
    printf '\n'
}

check_pass() { printf '  [\033[32m✓\033[0m] %s\n' "$1"; }
check_fail() { printf '  [\033[31m✗\033[0m] %s\n' "$1"; }

die() { printf '\033[31mError:\033[0m %s\n' "$1" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Step 1 — Banner + confirmation
# ---------------------------------------------------------------------------

print_banner

printf 'This will install lstack into: %s\n' "${CLAUDE_DIR}"
printf '\n'
printf 'What lstack touches:\n'
printf '  ~/.claude/CLAUDE.md        — global Claude Code instructions\n'
printf '  ~/.claude/settings.json    — hooks, spinner verbs, statusline\n'
printf '  ~/.claude/hooks/           — lifecycle hook scripts\n'
printf '  ~/.claude/scripts/         — helper scripts\n'
printf '  ~/.claude/skills/          — on-demand skill prompts\n'
printf '  ~/.claude/bin/lstack       — CLI tool\n'
printf '  ~/.claude/memory/          — memory index files (NOT personal data)\n'
printf '\n'
printf 'What lstack does NOT touch:\n'
printf '  ~/.claude/memory/preferences.md    — your personal preferences\n'
printf '  ~/.claude/memory/patterns.md       — your learned patterns\n'
printf '  ~/.claude/memory/lstack.db         — your persistent memory DB\n'
printf '  Any project .claude/ directories\n'
printf '\n'
printf 'Press Enter to continue or Ctrl+C to cancel. '
read -r _confirm

# ---------------------------------------------------------------------------
# Step 2 — Detect existing ~/.claude
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IS_LOCAL_REPO=false
if [ -f "${SCRIPT_DIR}/bin/lstack" ] && [ -f "${SCRIPT_DIR}/scripts/gen-settings.sh" ]; then
    IS_LOCAL_REPO=true
fi

if [ -d "${CLAUDE_DIR}" ]; then
    if [ -f "${CLAUDE_DIR}/.git-source" ]; then
        printf '\nExisting lstack install detected. Running upgrade instead.\n'
        git -C "${CLAUDE_DIR}" pull --ff-only origin main
        printf '\nUpgrade complete. Restart Claude Code to apply changes.\n'
        exit 0
    else
        printf '\n'
        printf '\033[33mWarning:\033[0m ~/.claude already exists and was not installed by lstack.\n'
        BACKUP_DIR="${HOME}/.claude.backup.$(date +%Y%m%d_%H%M%S)"
        printf 'A backup will be created at: %s\n' "${BACKUP_DIR}"
        printf 'Your existing setup will be preserved there.\n'
        printf '\n'
        printf 'Continue? [y/N] '
        read -r answer
        case "${answer}" in
            [yY]|[yY][eE][sS]) ;;
            *) printf 'Aborted.\n'; exit 0 ;;
        esac
        printf 'Creating backup...\n'
        cp -r "${CLAUDE_DIR}" "${BACKUP_DIR}"
        printf 'Backup created: %s\n' "${BACKUP_DIR}"
    fi
fi

# ---------------------------------------------------------------------------
# Step 3 — Clone or copy lstack files
# ---------------------------------------------------------------------------

printf '\nInstalling lstack files...\n'

if [ "${IS_LOCAL_REPO}" = true ]; then
    printf 'Source: local repo at %s\n' "${SCRIPT_DIR}"
    # Use rsync if available, fall back to cp
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --exclude='.git' "${SCRIPT_DIR}/" "${CLAUDE_DIR}/"
    else
        mkdir -p "${CLAUDE_DIR}"
        cp -r "${SCRIPT_DIR}/." "${CLAUDE_DIR}/"
        # Remove .git if it got copied (we manage it separately in step 6)
        rm -rf "${CLAUDE_DIR}/.git" 2>/dev/null || true
    fi
else
    printf 'Cloning from %s...\n' "${LSTACK_REPO}"
    git clone "${LSTACK_REPO}" "${CLAUDE_DIR}"
fi

# ---------------------------------------------------------------------------
# Step 4 — Set permissions
# ---------------------------------------------------------------------------

printf 'Setting permissions...\n'
chmod +x "${CLAUDE_DIR}/hooks/"*.sh 2>/dev/null || true
chmod +x "${CLAUDE_DIR}/scripts/"*.sh 2>/dev/null || true
chmod +x "${CLAUDE_DIR}/bin/lstack" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 5 — Detect OS and generate settings.json
# ---------------------------------------------------------------------------

printf 'Generating settings.json...\n'
bash "${CLAUDE_DIR}/scripts/gen-settings.sh" > "${CLAUDE_DIR}/settings.json"

# Detect OS for display
_OS="$(uname -s 2>/dev/null || echo 'Unknown')"
case "${_OS}" in
    Darwin) _OS_NAME="macOS" ;;
    Linux)  _OS_NAME="Linux" ;;
    MINGW*|MSYS*|CYGWIN*) _OS_NAME="Windows (Git Bash)" ;;
    *)      _OS_NAME="${_OS}" ;;
esac
printf 'Generated settings.json for %s\n' "${_OS_NAME}"

# Validate JSON
if python3 -m json.tool "${CLAUDE_DIR}/settings.json" > /dev/null 2>&1; then
    printf 'settings.json is valid.\n'
else
    printf '\033[31mError:\033[0m settings.json failed JSON validation.\n'
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 6 — Initialize git repo (enables lstack upgrade)
# ---------------------------------------------------------------------------

if [ ! -d "${CLAUDE_DIR}/.git" ]; then
    printf 'Initializing git repo in ~/.claude...\n'
    git -C "${CLAUDE_DIR}" init -b main 2>/dev/null || git -C "${CLAUDE_DIR}" init
    git -C "${CLAUDE_DIR}" remote add origin "${LSTACK_REPO}" 2>/dev/null || true
    git -C "${CLAUDE_DIR}" add -A
    git -C "${CLAUDE_DIR}" commit -m "lstack install" --quiet 2>/dev/null || true
fi

# Always write .git-source (marks this as an lstack install)
printf '%s\n' "${LSTACK_REPO}" > "${CLAUDE_DIR}/.git-source"

# ---------------------------------------------------------------------------
# Step 7 — Create memory scaffolding (never overwrite personal files)
# ---------------------------------------------------------------------------

printf 'Creating memory scaffolding...\n'
mkdir -p "${CLAUDE_DIR}/memory" "${CLAUDE_DIR}/logs"

# MEMORY.md — use the template from the repo if it exists, else create minimal
if [ ! -f "${CLAUDE_DIR}/memory/MEMORY.md" ]; then
    if [ -f "${CLAUDE_DIR}/memory/MEMORY.md.template" ]; then
        cp "${CLAUDE_DIR}/memory/MEMORY.md.template" "${CLAUDE_DIR}/memory/MEMORY.md"
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
    fi
fi

# Personal files — only create if absent
if [ ! -f "${CLAUDE_DIR}/memory/preferences.md" ]; then
    cat > "${CLAUDE_DIR}/memory/preferences.md" <<'PREFEOF'
# Preferences
<!-- Your personal preferences. Claude updates this as it learns about you. -->
<!-- Name, primary languages, verbosity, workflow style, etc. -->
PREFEOF
fi

if [ ! -f "${CLAUDE_DIR}/memory/patterns.md" ]; then
    cat > "${CLAUDE_DIR}/memory/patterns.md" <<'PATEOF'
# Patterns
<!-- Coding and workflow patterns Claude has observed in your work. -->

## Architecture patterns

## Testing patterns

## Workflow patterns
PATEOF
fi

if [ ! -f "${CLAUDE_DIR}/memory/projects.md" ]; then
    cat > "${CLAUDE_DIR}/memory/projects.md" <<'PROJEOF'
# Projects
<!-- Active projects and their context. -->
PROJEOF
fi

# ---------------------------------------------------------------------------
# Step 8 — Initialize persistent DB
# ---------------------------------------------------------------------------

printf 'Initializing persistent memory DB...\n'
_python="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
if [ -n "${_python}" ]; then
    "${_python}" "${CLAUDE_DIR}/scripts/db.py" init 2>/dev/null || true
    printf 'Persistent memory DB initialized at ~/.claude/memory/lstack.db\n'
else
    printf '\033[33mWarning:\033[0m python3 not found — DB init skipped. Install Python 3 and run: python3 ~/.claude/scripts/db.py init\n'
fi

# ---------------------------------------------------------------------------
# Step 9 — Run onboarding
# ---------------------------------------------------------------------------

printf '\n'
bash "${CLAUDE_DIR}/bin/lstack" onboard

# ---------------------------------------------------------------------------
# Step 10 — Post-install verification
# ---------------------------------------------------------------------------

printf '\n'
printf '=== Verifying installation ===\n'
printf '\n'

_failures=0

# Check 1: Hook scripts executable
_hooks_ok=true
for _h in "${CLAUDE_DIR}/hooks/"*.sh; do
    [ -f "${_h}" ] || continue
    if [ ! -x "${_h}" ]; then
        _hooks_ok=false
        break
    fi
done
if [ "${_hooks_ok}" = true ] && ls "${CLAUDE_DIR}/hooks/"*.sh >/dev/null 2>&1; then
    check_pass "Hook scripts executable"
else
    check_fail "Hook scripts not executable — run: chmod +x ~/.claude/hooks/*.sh"
    _failures=$(( _failures + 1 ))
fi

# Check 2: settings.json valid JSON
if python3 -m json.tool "${CLAUDE_DIR}/settings.json" >/dev/null 2>&1; then
    check_pass "settings.json valid JSON"
else
    check_fail "settings.json invalid — run: lstack settings"
    _failures=$(( _failures + 1 ))
fi

# Check 3: Python 3 found
_py_path="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
if [ -n "${_py_path}" ]; then
    check_pass "Python 3 found: ${_py_path}"
else
    check_fail "Python 3 not found — install python3"
    _failures=$(( _failures + 1 ))
fi

# Check 4: DB accessible
if [ -n "${_py_path}" ] && "${_py_path}" "${CLAUDE_DIR}/scripts/db.py" stats >/dev/null 2>&1; then
    check_pass "Persistent DB accessible"
else
    check_fail "DB not accessible — run: python3 ~/.claude/scripts/db.py init"
    _failures=$(( _failures + 1 ))
fi

# Check 5: lstack CLI works
if bash "${CLAUDE_DIR}/bin/lstack" help >/dev/null 2>&1; then
    check_pass "lstack CLI works"
else
    check_fail "lstack CLI failed — run: chmod +x ~/.claude/bin/lstack"
    _failures=$(( _failures + 1 ))
fi

printf '\n'

if [ "${_failures}" -eq 0 ]; then
    printf '╔══════════════════════════════════════════════════════════╗\n'
    printf '║  lstack installed successfully                           ║\n'
    printf '║                                                          ║\n'
    printf '║  Next steps:                                             ║\n'
    printf '║  1. Restart Claude Code                                  ║\n'
    printf '║  2. Open any project and run: lstack init                ║\n'
    printf '║  3. Check status anytime: lstack status                  ║\n'
    printf '╚══════════════════════════════════════════════════════════╝\n'
    printf '\n'
else
    printf '\033[33m%d check(s) failed.\033[0m Fix the issues above, then restart Claude Code.\n' "${_failures}"
    printf 'Run \033[1mlstack doctor\033[0m anytime to re-check.\n'
    exit 1
fi

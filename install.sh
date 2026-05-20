#!/usr/bin/env bash
# lstack installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/puukis/lstack/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/puukis/lstack/main/install.sh | bash -s -- --yes
#   bash /path/to/lstack/install.sh

set -euo pipefail

LSTACK_REPO="https://github.com/puukis/lstack"
CLAUDE_DIR="${HOME}/.claude"
_INSTALL_START="$(date +%s 2>/dev/null || echo 0)"

# ─── Color palette ────────────────────────────────────────────────────────────

BOLD='\033[1m'
ACCENT='\033[38;2;99;179;237m'        # sky blue
ACCENT2='\033[38;2;154;230;180m'      # mint green
INFO='\033[38;2;136;146;176m'         # text-secondary
SUCCESS='\033[38;2;72;199;142m'       # green
WARN='\033[38;2;250;176;5m'           # amber
ERROR='\033[38;2;252;82;82m'          # red
MUTED='\033[38;2;90;100;128m'         # muted
NC='\033[0m'

# ─── Flags ────────────────────────────────────────────────────────────────────

INTERACTIVE=true
NO_PROMPT=0
DRY_RUN=0
VERBOSE=0
HELP=0

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --yes|-y|--no-prompt) INTERACTIVE=false; NO_PROMPT=1; shift ;;
            --dry-run)            DRY_RUN=1; shift ;;
            --verbose)            VERBOSE=1; shift ;;
            --help|-h)            HELP=1; shift ;;
            *) shift ;;
        esac
    done
}

parse_args "$@"

_is_stdin_tty()  { [ -t 0 ]; }
_is_stdout_tty() { [ -t 1 ]; }

_is_non_interactive() {
    [[ "$NO_PROMPT" == "1" ]] || ! _is_stdin_tty
}

# Strip colors when not a TTY
if ! _is_stdout_tty; then
    BOLD=''; ACCENT=''; ACCENT2=''; INFO=''; SUCCESS=''; WARN=''
    ERROR=''; MUTED=''; NC=''
fi

# ─── Temp file tracking ───────────────────────────────────────────────────────

TMPFILES=()
_cleanup() {
    local f
    for f in "${TMPFILES[@]:-}"; do rm -rf "$f" 2>/dev/null || true; done
    _spin_stop
}
trap '_cleanup' EXIT INT TERM

_mktmp() { local f; f="$(mktemp)"; TMPFILES+=("$f"); echo "$f"; }

# ─── Downloader ───────────────────────────────────────────────────────────────

_download() {
    local url="$1" out="$2"
    if command -v curl &>/dev/null; then
        curl -fsSL --proto '=https' --tlsv1.2 --retry 3 --retry-delay 1 -o "$out" "$url"
    elif command -v wget &>/dev/null; then
        wget -q --https-only --secure-protocol=TLSv1_2 --tries=3 -O "$out" "$url"
    else
        return 1
    fi
}

# ─── Gum bootstrap ────────────────────────────────────────────────────────────

GUM=""
GUM_STATUS="skipped"
GUM_REASON=""
GUM_VERSION="0.17.0"

_gum_os() {
    case "$(uname -s 2>/dev/null)" in
        Darwin) echo "Darwin" ;;
        Linux)  echo "Linux"  ;;
        *)      echo "unsupported" ;;
    esac
}

_gum_arch() {
    case "$(uname -m 2>/dev/null)" in
        x86_64|amd64)   echo "x86_64" ;;
        arm64|aarch64)  echo "arm64"  ;;
        *)              echo "unknown" ;;
    esac
}

_verify_sha256() {
    local checksums="$1"
    if command -v sha256sum &>/dev/null; then
        sha256sum --ignore-missing -c "$checksums" &>/dev/null
    elif command -v shasum &>/dev/null; then
        shasum -a 256 --ignore-missing -c "$checksums" &>/dev/null
    else
        return 1
    fi
}

_bootstrap_gum() {
    GUM=""; GUM_STATUS="skipped"; GUM_REASON=""

    _is_non_interactive             && { GUM_REASON="non-interactive"; return 1; }
    ! _is_stdout_tty                && { GUM_REASON="not a TTY"; return 1; }
    [[ "${TERM:-dumb}" == "dumb" ]] && { GUM_REASON="dumb terminal"; return 1; }

    if command -v gum &>/dev/null; then
        GUM="gum"; GUM_STATUS="found"; GUM_REASON="already installed"; return 0
    fi

    command -v tar &>/dev/null || { GUM_REASON="tar not found"; return 1; }

    local os arch asset base tmpdir gum_path
    os="$(_gum_os)"; arch="$(_gum_arch)"
    [[ "$os" == "unsupported" || "$arch" == "unknown" ]] && { GUM_REASON="unsupported os/arch"; return 1; }

    asset="gum_${GUM_VERSION}_${os}_${arch}.tar.gz"
    base="https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}"
    tmpdir="$(mktemp -d)"; TMPFILES+=("$tmpdir")

    printf "${MUTED}·${NC} Preparing UI layer...\n"
    _download "${base}/${asset}"       "$tmpdir/$asset"    || { GUM_REASON="download failed"; return 1; }
    _download "${base}/checksums.txt"  "$tmpdir/checksums.txt" || { GUM_REASON="checksum unavailable"; return 1; }
    (cd "$tmpdir" && _verify_sha256 "checksums.txt")       || { GUM_REASON="checksum mismatch"; return 1; }
    tar -xzf "$tmpdir/$asset" -C "$tmpdir" &>/dev/null     || { GUM_REASON="extract failed"; return 1; }

    gum_path="$(find "$tmpdir" -type f -name gum 2>/dev/null | head -n1)"
    [[ -n "$gum_path" ]] || { GUM_REASON="binary missing after extract"; return 1; }
    chmod +x "$gum_path"
    [[ -x "$gum_path" ]] || { GUM_REASON="binary not executable"; return 1; }

    GUM="$gum_path"; GUM_STATUS="installed"; GUM_REASON="temp, verified"
    return 0
}

# ─── UI helpers ───────────────────────────────────────────────────────────────

ui_info() {
    local msg="$*"
    if [[ -n "$GUM" ]]; then "$GUM" log --level info "$msg"
    else printf "${MUTED}·${NC} %s\n" "$msg"; fi
}

ui_warn() {
    local msg="$*"
    if [[ -n "$GUM" ]]; then "$GUM" log --level warn "$msg"
    else printf "${WARN}⚠${NC} %s\n" "$msg"; fi
}

ui_success() {
    local msg="$*"
    if [[ -n "$GUM" ]]; then
        printf "%s %s\n" "$("$GUM" style --foreground "#48c78e" --bold "✓")" "$msg"
    else
        printf "${SUCCESS}✓${NC} %s\n" "$msg"
    fi
}

ui_error() {
    local msg="$*"
    if [[ -n "$GUM" ]]; then "$GUM" log --level error "$msg"
    else printf "${ERROR}✗${NC} %s\n" "$msg" >&2; fi
}

ui_kv() {
    local key="$1" val="$2"
    if [[ -n "$GUM" ]]; then
        local k v
        k="$("$GUM" style --foreground "#5a6480" --width 22 "$key")"
        v="$("$GUM" style --bold "$val")"
        "$GUM" join --horizontal "$k" "$v"
    else
        printf "${MUTED}%-22s${NC} %s\n" "$key" "$val"
    fi
}

STAGE_TOTAL=8
STAGE_CUR=0

ui_stage() {
    STAGE_CUR=$(( STAGE_CUR + 1 ))
    local title="[$STAGE_CUR/$STAGE_TOTAL] $1"
    if [[ -n "$GUM" ]]; then
        printf '\n'
        "$GUM" style --bold --foreground "#63b3ed" --padding "0 0" "$title"
        printf '\n'
    else
        printf '\n'
        printf "  ${ACCENT}${BOLD}%s${NC}\n" "$title"
        printf '\n'
    fi
}

check_pass() { printf "  ${SUCCESS}✓${NC}  %-42s ${MUTED}OK${NC}\n" "$1"; }
check_fail() { printf "  ${ERROR}✗${NC}  %-42s ${ERROR}FAIL${NC}\n" "$1"; }
check_warn() { printf "  ${WARN}⚠${NC}  %-42s ${WARN}WARN${NC}\n" "$1"; }

# ─── Spinner (pure bash fallback when gum unavailable) ────────────────────────

_spin_pid=''

_do_spin() {
    local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local i=0
    tput civis 2>/dev/null || true
    while true; do
        printf "\r  ${ACCENT}${frames[$(( i % 10 ))]}${NC}  %s  " "$1"
        i=$(( i + 1 ))
        sleep 0.1
    done
}

_spin_start() {
    if _is_stdout_tty && [[ -z "$GUM" ]]; then
        _do_spin "$1" &
        _spin_pid=$!
    elif [[ -z "$GUM" ]]; then
        ui_info "$1"
    fi
}

_spin_stop() {
    if [[ -n "${_spin_pid}" ]]; then
        kill "${_spin_pid}" 2>/dev/null || true
        wait "${_spin_pid}" 2>/dev/null || true
        _spin_pid=''
        printf '\r\033[K'
        tput cnorm 2>/dev/null || true
    fi
}

_run_quiet() {
    local title="$1"; shift
    local log; log="$(_mktmp)"

    if [[ -n "$GUM" ]] && _is_stdout_tty; then
        local cmd_q log_q
        printf -v cmd_q '%q ' "$@"
        printf -v log_q '%q'  "$log"
        "$GUM" spin --spinner dot --title "$title" -- bash -c "${cmd_q}>${log_q} 2>&1"
        return $?
    fi

    _spin_start "$title"
    if "$@" >"$log" 2>&1; then
        _spin_stop
        return 0
    fi
    _spin_stop
    ui_error "$title failed"
    [[ "$VERBOSE" == "1" ]] && cat "$log" >&2 || tail -n 20 "$log" >&2
    return 1
}

# ─── Script-dir detection ─────────────────────────────────────────────────────

_realpath() {
    if command -v realpath &>/dev/null; then realpath "$1"
    elif [ -d "$1" ]; then (cd "$1" && pwd)
    else (cd "$(dirname "$1")" && printf '%s/%s\n' "$(pwd)" "$(basename "$1")")
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

# ─── Elapsed time ─────────────────────────────────────────────────────────────

_elapsed() {
    local now secs
    now="$(date +%s 2>/dev/null || echo 0)"
    secs=$(( now - _INSTALL_START ))
    if [ "${secs}" -lt 60 ]; then printf '%ds' "${secs}"
    else printf '%dm %ds' "$(( secs / 60 ))" "$(( secs % 60 ))"; fi
}

# ─── Taglines ─────────────────────────────────────────────────────────────────

TAGLINES=(
    "Your terminal finally has a brain."
    "Claude Code, fully loaded."
    "Hooks, memory, skills — all wired in."
    "Engineering environment, not a vibe."
    "The scaffolding Claude Code deserves."
    "Fewer tabs. More flow."
    "Config once, ship forever."
    "Because \`claude\` alone is just the beginning."
    "Your context window has a guardian angel now."
    "One install. Zero babysitting."
    "Persistent memory. Session hooks. Pure signal."
    "The dev environment that remembers what you told it."
    "Less setup per project. More coding."
    "Hooks that enforce quality so you don't have to."
    "Where Claude Code gets its superpowers."
)

_pick_tagline() {
    local idx=$(( RANDOM % ${#TAGLINES[@]} ))
    echo "${TAGLINES[$idx]}"
}

TAGLINE="$(_pick_tagline)"

# ─── Banner ───────────────────────────────────────────────────────────────────

print_banner() {
    if [[ -n "$GUM" ]]; then
        local title tagline hint card
        title="$("$GUM" style --foreground "#63b3ed" --bold "⚡ lstack installer")"
        tagline="$("$GUM" style --foreground "#8892b0" "$TAGLINE")"
        hint="$("$GUM" style --foreground "#5a6480" "Claude Code Engineering Environment")"
        card="$(printf '%s\n%s\n%s' "$title" "$tagline" "$hint")"
        "$GUM" style --border rounded --border-foreground "#63b3ed" --padding "1 2" "$card"
        printf '\n'
        return
    fi

    printf '\n'
    printf "  ${MUTED}┌──────────────────────────────────────────────────────────┐${NC}\n"
    printf "  ${MUTED}│${NC}                                                          ${MUTED}│${NC}\n"
    printf "  ${MUTED}│${NC}   ${ACCENT}${BOLD}⚡ lstack${NC}  ·  Claude Code Engineering Environment      ${MUTED}│${NC}\n"
    printf "  ${MUTED}│${NC}   ${MUTED}%s${NC}" "$TAGLINE"
    # pad tagline to fill box width
    local tlen=${#TAGLINE}
    local pad=$(( 54 - tlen ))
    printf '%*s' "$pad" ''
    printf "${MUTED}│${NC}\n"
    printf "  ${MUTED}│${NC}                                                          ${MUTED}│${NC}\n"
    printf "  ${MUTED}└──────────────────────────────────────────────────────────┘${NC}\n"
    printf '\n'
}

# ─── Help ─────────────────────────────────────────────────────────────────────

print_usage() {
    cat <<EOF
lstack installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/puukis/lstack/main/install.sh | bash
  bash install.sh [options]

Options:
  --yes, -y, --no-prompt   Non-interactive (skip confirmation prompts)
  --dry-run                Show what would happen without making changes
  --verbose                Show full output from sub-commands
  --help, -h               Show this help

Environment variables:
  LSTACK_REPO=<url>        Override git repository (default: GitHub)
EOF
}

if [[ "$HELP" == "1" ]]; then print_usage; exit 0; fi

# ─── Init UI ──────────────────────────────────────────────────────────────────

_bootstrap_gum || true
print_banner

if [[ "$GUM_STATUS" == "installed" ]]; then
    ui_success "UI layer ready (gum v${GUM_VERSION})"
elif [[ "$GUM_STATUS" == "found" ]]; then
    ui_success "gum available (${GUM_REASON})"
elif [[ -n "$GUM_REASON" && "$GUM_REASON" != "non-interactive" ]]; then
    ui_info "Running in classic mode (${GUM_REASON})"
fi

# ─── Install plan ─────────────────────────────────────────────────────────────

printf '\n'
if [[ -n "$GUM" ]]; then
    "$GUM" style --bold --foreground "#63b3ed" "Install plan"
else
    printf "  ${ACCENT}${BOLD}Install plan${NC}\n"
fi
printf '\n'

_OS="$(uname -s 2>/dev/null || echo Unknown)"
case "$_OS" in Darwin) _OS_NAME="macOS";; Linux) _OS_NAME="Linux";; *) _OS_NAME="$_OS";; esac
_INSTALL_SOURCE="$LSTACK_REPO"
[[ "$IS_LOCAL_REPO" == "true" ]] && _INSTALL_SOURCE="local repo (${SCRIPT_DIR})"

ui_kv "Install to"    "$CLAUDE_DIR"
ui_kv "Source"        "$_INSTALL_SOURCE"
ui_kv "OS"            "$_OS_NAME"
[[ "$DRY_RUN" == "1" ]] && ui_kv "Dry run" "yes — no changes will be made"
printf '\n'

if [[ -n "$GUM" ]]; then
    "$GUM" style --foreground "#5a6480" "Files installed:"
else
    printf "  ${MUTED}Files installed:${NC}\n"
fi
for f in \
    "~/.claude/CLAUDE.md          — global Claude Code instructions" \
    "~/.claude/settings.json      — hooks, spinner, statusline" \
    "~/.claude/hooks/             — lifecycle hook scripts" \
    "~/.claude/scripts/           — helper scripts" \
    "~/.claude/skills/            — on-demand skill prompts" \
    "~/.claude/bin/lstack         — CLI tool" \
    "~/.claude/memory/            — memory index files"
do
    printf "  ${MUTED}  %s${NC}\n" "$f"
done
printf '\n'

printf "  ${MUTED}Never touched:  personal memory files, project .claude/ dirs${NC}\n"
printf '\n'

if [[ "$DRY_RUN" == "1" ]]; then
    ui_success "Dry run complete — no changes made"
    exit 0
fi

if ! _is_non_interactive; then
    if [[ -n "$GUM" ]]; then
        "$GUM" confirm "Proceed with installation?" || { printf '\n  Aborted.\n\n'; exit 0; }
    else
        printf "  Press ${BOLD}Enter${NC} to continue or ${BOLD}Ctrl+C${NC} to abort. "
        read -r _confirm
    fi
    printf '\n'
else
    ui_info "Non-interactive mode — skipping confirmation"
fi

# ─── Step 1: Prerequisites ────────────────────────────────────────────────────

ui_stage "Checking prerequisites"

_prereq_failures=0

if command -v git &>/dev/null; then
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
    check_warn "python3 not found — persistent DB will be skipped"
fi

_bash_ver="$(bash --version 2>/dev/null | head -1 | sed 's/.*version //' | sed 's/ .*//')"
check_pass "bash (${_bash_ver})"

if [ "${_prereq_failures}" -gt 0 ]; then
    ui_error "Missing required tools — install them and re-run"
    exit 1
fi

# ─── Step 2: Detect existing install ─────────────────────────────────────────

ui_stage "Checking for existing installation"

BACKUP_DIR=''
IS_UPGRADE=false

if [ -d "${CLAUDE_DIR}" ]; then
    if [ -f "${CLAUDE_DIR}/.git-source" ]; then
        IS_UPGRADE=true
        ui_success "Existing lstack install detected — upgrading"
        printf '\n'
        _run_quiet "Pulling latest from origin/main" \
            git -C "${CLAUDE_DIR}" pull --ff-only origin main || {
            ui_warn "Fast-forward failed — local changes present"
            ui_info "To upgrade manually: git -C ~/.claude reset --hard origin/main"
        }
        printf '\n'
        printf "  ${MUTED}Restart Claude Code to apply changes.${NC}\n\n"
        exit 0
    else
        ui_warn "~/.claude exists but was not installed by lstack"
        BACKUP_DIR="${HOME}/.claude.backup.$(date +%Y%m%d_%H%M%S)"
        ui_info "Backup destination: ${BACKUP_DIR}"
        printf '\n'
        if ! _is_non_interactive; then
            if [[ -n "$GUM" ]]; then
                "$GUM" confirm "Create backup and continue?" || { printf '\n  Aborted.\n\n'; exit 0; }
            else
                printf "  Create backup and continue? [${BOLD}y${NC}/N] "
                read -r _answer
                case "$_answer" in [yY]*) ;; *) printf '\n  Aborted.\n\n'; exit 0 ;; esac
            fi
            printf '\n'
        fi
        _run_quiet "Creating backup" cp -r "${CLAUDE_DIR}" "${BACKUP_DIR}"
        ui_success "Backup created at ${BACKUP_DIR}"
    fi
else
    ui_success "Clean install — no existing ~/.claude"
fi

# ─── Step 3: Install files ────────────────────────────────────────────────────

ui_stage "Installing lstack files"

if [ "${IS_LOCAL_REPO}" = true ]; then
    ui_info "Source: local repo at ${SCRIPT_DIR}"
    if command -v rsync &>/dev/null; then
        _run_quiet "Copying files" rsync -a --exclude='.git' "${SCRIPT_DIR}/" "${CLAUDE_DIR}/"
    else
        _run_quiet "Copying files" bash -c "mkdir -p '${CLAUDE_DIR}' && cp -r '${SCRIPT_DIR}/.' '${CLAUDE_DIR}/' && rm -rf '${CLAUDE_DIR}/.git'"
    fi
    ui_success "Files copied from local repo"
else
    ui_info "Source: ${LSTACK_REPO}"
    _run_quiet "Cloning repository" git clone --quiet "${LSTACK_REPO}" "${CLAUDE_DIR}"
    ui_success "Repository cloned"
fi

# ─── Step 4: Permissions + settings ──────────────────────────────────────────

ui_stage "Configuring permissions and settings"

_run_quiet "Setting executable permissions" bash -c "
    chmod +x '${CLAUDE_DIR}/hooks/'*.sh   2>/dev/null || true
    chmod +x '${CLAUDE_DIR}/scripts/'*.sh 2>/dev/null || true
    chmod +x '${CLAUDE_DIR}/bin/lstack'   2>/dev/null || true
"
ui_success "Executable bits set"

_run_quiet "Generating settings.json for ${_OS_NAME}" \
    bash -c "bash '${CLAUDE_DIR}/scripts/gen-settings.sh' > '${CLAUDE_DIR}/settings.json'"

if python3 -m json.tool "${CLAUDE_DIR}/settings.json" >/dev/null 2>&1; then
    ui_success "settings.json generated and validated"
else
    ui_error "settings.json failed JSON validation"
    exit 1
fi

# ─── Step 5: Version tracking ─────────────────────────────────────────────────

ui_stage "Initializing version tracking"

if [ ! -d "${CLAUDE_DIR}/.git" ]; then
    _run_quiet "Initializing git repo in ~/.claude" bash -c "
        git -C '${CLAUDE_DIR}' init -b main 2>/dev/null || git -C '${CLAUDE_DIR}' init
        git -C '${CLAUDE_DIR}' remote add origin '${LSTACK_REPO}' 2>/dev/null || true
        git -C '${CLAUDE_DIR}' add -A
        git -C '${CLAUDE_DIR}' commit -m 'lstack install' --quiet 2>/dev/null || true
    "
    ui_success "Git repo initialized in ~/.claude"
else
    ui_success "Git repo already present"
fi

printf '%s\n' "${LSTACK_REPO}" > "${CLAUDE_DIR}/.git-source"

# ─── Step 6: Memory scaffolding ───────────────────────────────────────────────

ui_stage "Creating memory scaffolding"

mkdir -p "${CLAUDE_DIR}/memory" "${CLAUDE_DIR}/logs"

if [ ! -f "${CLAUDE_DIR}/memory/MEMORY.md" ]; then
    if [ -f "${CLAUDE_DIR}/memory/MEMORY.md.template" ]; then
        cp "${CLAUDE_DIR}/memory/MEMORY.md.template" "${CLAUDE_DIR}/memory/MEMORY.md"
        ui_success "MEMORY.md created from template"
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
        ui_success "MEMORY.md initialized"
    fi
else
    ui_success "MEMORY.md already exists — not overwritten"
fi

_scaffold_file() {
    local path="$1" label="$2" content="$3"
    if [ ! -f "${path}" ]; then
        printf '%s' "${content}" > "${path}"
        ui_success "${label} created"
    else
        ui_info "${label} already exists — keeping yours"
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

ui_stage "Initializing persistent memory database"

if [ -n "${_py_path}" ]; then
    _run_quiet "Initializing lstack.db" \
        bash -c "'${_py_path}' '${CLAUDE_DIR}/scripts/db.py' init 2>/dev/null || true"
    ui_success "Persistent DB ready at ~/.claude/memory/lstack.db"
else
    ui_warn "python3 not found — DB init skipped"
    ui_info "Fix: install Python 3, then run: python3 ~/.claude/scripts/db.py init"
fi

# ─── Add lstack to PATH ───────────────────────────────────────────────────────

_lstack_bin="${CLAUDE_DIR}/bin"
_path_export='export PATH="$HOME/.claude/bin:$PATH"'
_path_fish="fish_add_path ~/.claude/bin"

_add_to_path() {
    local rc="$1" line="$2"
    [ -f "${rc}" ] && grep -qF "${line}" "${rc}" 2>/dev/null && return 0
    printf '\n# lstack CLI\n%s\n' "${line}" >> "${rc}"
    printf 'true'
}

case ":${PATH}:" in
    *":${_lstack_bin}:"*)
        ui_info "lstack already in PATH"
        ;;
    *)
        _shell_name="$(basename "${SHELL:-bash}")"
        _added_to=""
        case "${_shell_name}" in
            fish)
                _fish_cfg="${HOME}/.config/fish/config.fish"
                [[ "$(_add_to_path "${_fish_cfg}" "${_path_fish}")" == "true" ]] && _added_to="${_fish_cfg}"
                ;;
            zsh)
                [[ "$(_add_to_path "${HOME}/.zshrc" "${_path_export}")" == "true" ]] && _added_to="${HOME}/.zshrc"
                ;;
            *)
                [[ "$(_add_to_path "${HOME}/.bashrc" "${_path_export}")" == "true" ]] && _added_to="${HOME}/.bashrc"
                ;;
        esac
        if [ -n "${_added_to}" ]; then
            ui_success "Added lstack to PATH in ${_added_to}"
            ui_info "Run: source ${_added_to}  (or restart your terminal)"
        else
            ui_info "lstack PATH entry already present"
        fi
        ;;
esac

# ─── Step 8: Verification ─────────────────────────────────────────────────────

ui_stage "Verifying installation"

_failures=0

_hooks_ok=true
for _h in "${CLAUDE_DIR}/hooks/"*.sh; do
    [ -f "${_h}" ] || continue
    [ -x "${_h}" ] || { _hooks_ok=false; break; }
done
if "${_hooks_ok}" && ls "${CLAUDE_DIR}/hooks/"*.sh &>/dev/null; then
    check_pass "Hook scripts executable"
else
    check_fail "Hook scripts not executable"
    ui_info "Fix: chmod +x ~/.claude/hooks/*.sh"
    _failures=$(( _failures + 1 ))
fi

if python3 -m json.tool "${CLAUDE_DIR}/settings.json" &>/dev/null; then
    check_pass "settings.json valid JSON"
else
    check_fail "settings.json invalid"
    _failures=$(( _failures + 1 ))
fi

if [ -n "${_py_path}" ]; then
    check_pass "Python 3 available"
else
    check_warn "Python 3 not found"
fi

if [ -n "${_py_path}" ] && "${_py_path}" "${CLAUDE_DIR}/scripts/db.py" stats &>/dev/null; then
    check_pass "Persistent DB accessible"
else
    check_fail "Persistent DB not accessible"
    ui_info "Fix: python3 ~/.claude/scripts/db.py init"
    _failures=$(( _failures + 1 ))
fi

if bash "${CLAUDE_DIR}/bin/lstack" help &>/dev/null; then
    check_pass "lstack CLI works"
else
    check_fail "lstack CLI failed"
    ui_info "Fix: chmod +x ~/.claude/bin/lstack"
    _failures=$(( _failures + 1 ))
fi

# ─── Onboarding ───────────────────────────────────────────────────────────────

_elapsed_str="$(_elapsed)"
printf '\n'

if [ "${_failures}" -eq 0 ]; then
    if [[ -n "$GUM" ]]; then
        _success_msg="$("$GUM" style --bold --foreground "#48c78e" "✓  lstack installed successfully")"
        _time_msg="$("$GUM" style --foreground "#5a6480" "Completed in ${_elapsed_str}")"
        _card="$(printf '%s\n\n%s' "$_success_msg" "$_time_msg")"
        "$GUM" style --border rounded --border-foreground "#48c78e" --padding "1 2" "$_card"
    else
        printf "  ${MUTED}┌──────────────────────────────────────────────────────────┐${NC}\n"
        printf "  ${MUTED}│${NC}                                                          ${MUTED}│${NC}\n"
        printf "  ${MUTED}│${NC}   ${SUCCESS}${BOLD}✓  lstack installed successfully${NC}                       ${MUTED}│${NC}\n"
        printf "  ${MUTED}│${NC}                                                          ${MUTED}│${NC}\n"
        printf "  ${MUTED}│${NC}   ${MUTED}Completed in %s${NC}                                        ${MUTED}│${NC}\n" "${_elapsed_str}"
        printf "  ${MUTED}│${NC}                                                          ${MUTED}│${NC}\n"
        printf "  ${MUTED}└──────────────────────────────────────────────────────────┘${NC}\n"
    fi
    printf '\n'

    # Run interactive onboarding
    bash "${CLAUDE_DIR}/bin/lstack" onboard

    printf '\n'
    if [[ -n "$GUM" ]]; then
        "$GUM" style --bold --foreground "#63b3ed" "Next steps"
    else
        printf "  ${ACCENT}${BOLD}Next steps${NC}\n"
    fi
    printf '\n'
    ui_kv "1. Restart Claude Code"  "apply hooks and settings"
    ui_kv "2. Open a project"       "run: lstack init"
    ui_kv "3. Check health"         "run: lstack doctor"
    ui_kv "4. Update lstack"        "run: lstack upgrade"
    printf '\n'
    printf "  ${MUTED}Docs: ${LSTACK_REPO}${NC}\n"
    printf '\n'
else
    printf "  ${WARN}${BOLD}%d check(s) failed.${NC}  Fix the issues above, then restart Claude Code.\n" "${_failures}"
    printf "  Run ${BOLD}lstack doctor${NC} anytime to re-check.\n"
    printf '\n'
    exit 1
fi

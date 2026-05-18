# lstack — personal Claude Code environment

A portable hook and tooling layer for Claude Code. Provides loop detection,
bash safety gates, auto-formatting, memory management, and session logging.

## Platform support

- **macOS**: native bash, all features supported
- **Linux**: native bash, all features supported
- **Windows**: Git Bash (bundled with Git for Windows). Run `lstack settings`
  after install to regenerate settings.json with correct Windows paths. The
  statusline falls back to plain text (no ANSI colors) on Windows terminals.

## Install

### One-liner (macOS / Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/puukis/lstack/main/install.sh | bash
```

### Manual

```bash
git clone https://github.com/puukis/lstack /tmp/lstack
bash /tmp/lstack/install.sh
```

### Windows (Git Bash)

```bash
git clone https://github.com/puukis/lstack /tmp/lstack
bash /tmp/lstack/install.sh
# When prompted, run: lstack settings
# This regenerates settings.json with correct Windows paths
```

### Upgrading

```bash
lstack upgrade    # pulls latest from git and regenerates settings
```

### Existing ~/.claude setup

The installer detects an existing `~/.claude` directory and creates a
timestamped backup before installing. Your personal memory files
(`preferences.md`, `patterns.md`, `lstack.db`) are never overwritten.

### After install

1. Restart Claude Code
2. In any project: `lstack init`
3. Verify: `lstack doctor`

## Commands

| Command              | Description                                     |
|----------------------|-------------------------------------------------|
| `lstack init`        | Scaffold `.claude/` in current project          |
| `lstack settings`    | Regenerate settings.json for the current OS     |
| `lstack doctor`      | Diagnose installation health                    |
| `lstack onboard`     | Interactive first-run setup                     |
| `lstack memory`      | Open project or global MEMORY.md in `$EDITOR`  |
| `lstack logs`        | Tail tool-calls.log with color                  |
| `lstack status`      | Hook health, memory sizes, session timestamps   |
| `lstack clean`       | Prune logs >30 days; remove dead loop state     |
| `lstack upgrade`     | Pull latest lstack from git origin              |

## Hooks

| Hook             | File                        | Purpose                              |
|------------------|-----------------------------|--------------------------------------|
| SessionStart     | `hooks/session-start.sh`    | Load memory context, log session     |
| PreToolUse       | `hooks/pre-tool.sh`         | Loop detection, bash safety gates    |
| PostToolUse      | `hooks/post-tool.sh`        | Auto-format modified files           |
| PreCompact       | `hooks/pre-compact.sh`      | Generate handover before compaction  |
| Stop             | `hooks/stop.sh`             | Run project tests before finishing   |
| UserPromptSubmit | `scripts/token-budget.sh`   | Warn on high context usage           |

## Portability

All hooks source `scripts/os.sh` which provides:

- `OS` — `macos`, `linux`, or `windows`
- `PYTHON` — path to a working Python 3 interpreter
- `iso_now()` — portable UTC ISO 8601 timestamp
- `hash_string <str>` — portable SHA-256 hash
- `file_mtime <path>` — portable file mtime (seconds since epoch)
- `sed_inplace <expr> <file>` — portable in-place sed

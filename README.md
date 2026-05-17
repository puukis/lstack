# lstack — personal Claude Code environment

A portable hook and tooling layer for Claude Code. Provides loop detection,
bash safety gates, auto-formatting, memory management, and session logging.

## Platform support

- **macOS**: native bash, all features supported
- **Linux**: native bash, all features supported
- **Windows**: requires WSL2 with bash. Run `lstack settings` after install
  to regenerate settings.json with WSL-wrapped commands. The statusline
  falls back to plain text (no ANSI colors) on Windows terminals.

## Install

```bash
# macOS / Linux
git clone https://github.com/puukis/lstack ~/.claude
chmod +x ~/.claude/bin/lstack ~/.claude/hooks/*.sh ~/.claude/scripts/*.sh
bash ~/.claude/bin/lstack init
```

## Windows install

1. Install WSL2 and confirm bash is available: `wsl bash --version`
2. Clone into WSL home: `wsl git clone https://github.com/puukis/lstack ~/.claude`
3. In Claude Code on Windows, run: `wsl bash ~/.claude/bin/lstack init`
4. Run: `wsl bash ~/.claude/bin/lstack settings`
   This writes `C:\Users\<you>\.claude\settings.json` with WSL-wrapped commands.

> **Note:** Inside WSL, `~/.claude` maps to the Linux home directory, not
> `C:\Users\<you>\.claude`. The `wsl`-wrapped hook commands in settings.json
> reach into WSL's filesystem automatically.

## Commands

| Command           | Description                                     |
|-------------------|-------------------------------------------------|
| `lstack init`     | Scaffold `.claude/` in current project          |
| `lstack settings` | Regenerate settings.json for the current OS     |
| `lstack memory`   | Open project or global MEMORY.md in `$EDITOR`  |
| `lstack logs`     | Tail tool-calls.log with color                  |
| `lstack status`   | Hook health, memory sizes, session timestamps   |
| `lstack clean`    | Prune logs >30 days; remove dead loop state     |

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

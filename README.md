# lstack

A personal Claude Code environment that actually enforces things.

[![Stars](https://img.shields.io/github/stars/puukis/lstack?style=flat-square)](https://github.com/puukis/lstack/stargazers)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey?style=flat-square)](#platform-support)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-compatible-orange?style=flat-square)](https://claude.ai/code)

[Install](#install) | [Skills](#skills) | [Hooks](#hooks) | [Memory](#memory) | [CLI](#cli) | [Why lstack](#why-lstack)

---

## What it is

lstack is a portable ~/.claude environment for Claude Code. It adds persistent SQLite memory across sessions, loop detection, bash safety gates, auto-formatting, 15 on-demand skills, and a custom statusline — all working through Claude Code's native hook system.

No runtime. No daemon. No dependencies beyond bash, python3, and git.

---

## Install

One-liner:

    curl -fsSL https://raw.githubusercontent.com/puukis/lstack/main/install.sh | bash

Or manually:

    git clone https://github.com/puukis/lstack /tmp/lstack
    bash /tmp/lstack/install.sh

The installer detects your OS, generates the correct settings.json, initializes the memory database, and runs interactive onboarding. Existing ~/.claude setups are backed up with a timestamp before anything is written.

After install: restart Claude Code, then run `lstack init` in any project.

Windows: runs in Git Bash. All hooks use native Windows Python. No WSL required.

---

## Why lstack

| Feature                          | Vanilla CC | gstack | Superpowers | lstack |
|----------------------------------|------------|--------|-------------|--------|
| Persistent memory (SQLite)       | —          | —      | —           | yes    |
| Mid-session memory injection     | —          | —      | —           | yes    |
| Loop detection                   | —          | —      | —           | yes    |
| Token budget warnings            | —          | —      | —           | yes    |
| File re-read deduplication       | —          | —      | —           | yes    |
| Bash safety gates                | —          | —      | —           | yes    |
| Auto-formatter on write          | —          | —      | —           | yes    |
| PreCompact handover summary      | —          | —      | —           | yes    |
| Auto-extract session learnings   | —          | —      | —           | yes    |
| Git-aware context injection      | —          | —      | —           | yes    |
| Intent detection (auto-skills)   | —          | —      | yes         | yes    |
| Role personas                    | —          | yes    | yes         | yes    |
| Spec-first development           | —          | —      | yes         | yes    |
| Windows (Git Bash)               | —          | —      | —           | yes    |
| No daemon / no runtime           | yes        | yes    | yes         | yes    |

---

## Skills

| Skill          | Auto-activates when                          | Purpose                                                        |
|----------------|----------------------------------------------|----------------------------------------------------------------|
| /interrogate   | vague or large-scoped request                | Socratic one-question-at-a-time requirement clarification      |
| /blueprint     | requirements clear, no spec exists           | writes .blueprint.md before any code                           |
| /planner       | explicitly invoked                           | structured task breakdown with complexity estimates            |
| /build         | explicitly invoked                           | plan then implement with hard approval gate between phases     |
| /engineer      | explicitly invoked                           | production code: reads patterns first, runs tests after        |
| /reviewer      | review or LGTM mentioned                     | numbered findings: [N] [SEVERITY] [file:line]                  |
| /refactor      | explicitly invoked                           | improves structure without changing behavior                   |
| /test          | explicitly invoked                           | tests only, never touches source files                         |
| /debug         | bug or error described                       | reproduce, isolate, hypothesize, verify, state root cause      |
| /ship          | explicitly invoked                           | 5-point checklist before any release                           |
| /security      | auth, tokens, or deploy mentioned            | scans secrets, injection, bad deps                             |
| /architect     | new systems or large features                | ADRs and ARCHITECTURE.md before code                           |
| /parallel      | explicitly invoked                           | up to 3 sub-agents in isolated git worktrees                   |
| /remember      | explicitly invoked                           | stores a finding in persistent memory                          |
| /forget        | explicitly invoked                           | deletes matching observations from memory                      |

---

## Hooks

| Hook                      | Event                  | What it enforces                                           |
|---------------------------|------------------------|------------------------------------------------------------|
| hooks/session-start.sh    | Session opens          | Injects memory and git context                             |
| hooks/pre-tool.sh         | Before any tool call   | Loop detection, safety gates, memory lookup, re-read warnings |
| hooks/post-tool.sh        | After Write/Edit       | Auto-formats files, memory signal detector                 |
| hooks/pre-compact.sh      | Before compaction      | Saves handover summary via fresh subprocess                |
| hooks/stop.sh             | Session ends           | Runs project tests, stores session learnings in SQLite     |
| scripts/token-budget.sh   | Each prompt            | Warns at 60% context, alerts at 80%                        |

---

## Memory

lstack uses SQLite with FTS5 full-text search for persistent memory.

DB location: `~/.claude/memory/lstack.db`

Automatic injection points:

- **Session start**: recent observations for the current project are injected before the first message.
- **Mid-session**: when Claude reads a file or runs a command, relevant past context is retrieved and injected before the tool executes. Rate-limited to one injection per 15 tool calls.
- **Session end**: Stop hook extracts up to 3 learnings and stores them as observations automatically.

Manual controls:

    lstack search "jwt auth"
    lstack memory stats
    lstack memory prune --days 90

From inside Claude Code, use `/remember` to store a finding mid-session, or `/forget` to delete matching observations.

---

## CLI

| Command               | Description                                      |
|-----------------------|--------------------------------------------------|
| lstack init           | Scaffold .claude/ in the current project         |
| lstack doctor         | Diagnose installation health                     |
| lstack onboard        | Interactive first-run setup                      |
| lstack settings       | Regenerate settings.json for the current OS      |
| lstack search [query] | Search persistent memory                         |
| lstack memory stats   | Show DB statistics                               |
| lstack memory prune   | Delete old observations                          |
| lstack logs           | Tail tool-calls.log with color                   |
| lstack status         | Hook health, memory sizes, session timestamps    |
| lstack dashboard      | Live display of parallel agent worktrees         |
| lstack clean          | Prune logs and dead loop state files             |
| lstack upgrade        | Pull latest lstack from git                      |
| lstack publish        | Package lstack for sharing (strips personal data)|

---

## Platform support

| Platform | Status            | Notes                                                                 |
|----------|-------------------|-----------------------------------------------------------------------|
| macOS    | Fully supported   | Native bash, all features                                             |
| Linux    | Fully supported   | Native bash, all features                                             |
| Windows  | Supported         | Git Bash required. Hooks use native Windows Python. Statusline uses statusline.py. Run `lstack settings` after install. |

---

## Directory structure

    ~/.claude/
    ├── CLAUDE.md                  Global instructions (loaded every session)
    ├── settings.json              Hooks, spinner verbs, statusline, MCP config
    ├── hooks/
    │   ├── session-start.sh       Memory and git context injection
    │   ├── pre-tool.sh            Loop detection, safety gates, memory lookup
    │   ├── post-tool.sh           Auto-formatter, memory signal detector
    │   ├── pre-compact.sh         Handover summary before compaction
    │   └── stop.sh                Test runner and learning extractor
    ├── scripts/
    │   ├── os.sh                  Portable OS detection and helpers
    │   ├── db.py                  SQLite memory operations
    │   ├── statusline.py          Windows statusline (native Python)
    │   ├── statusline.sh          macOS and Linux statusline
    │   ├── token-budget.sh        Context usage warnings
    │   ├── gen-settings.sh        OS-aware settings.json generator
    │   └── dashboard.sh           Parallel agent monitor
    ├── skills/                    15 skill subdirectories (SKILL.md each)
    ├── memory/
    │   ├── MEMORY.md              Global memory index
    │   └── lstack.db              SQLite persistent memory (gitignored)
    └── bin/lstack                 CLI

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Star history

[![Star History Chart](https://api.star-history.com/svg?repos=puukis/lstack&type=Date)](https://star-history.com/#puukis/lstack&Date)

---

## License

MIT. See [LICENSE](LICENSE).

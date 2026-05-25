# lstack

A personal Claude Code environment that actually enforces things.

[![Stars](https://img.shields.io/github/stars/puukis/lstack?style=flat-square)](https://github.com/puukis/lstack/stargazers)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey?style=flat-square)](#platform-support)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-compatible-orange?style=flat-square)](https://claude.ai/code)

[Install](#install) | [Skills](#skills) | [Hooks](#hooks) | [Memory](#memory) | [CLI](#cli) | [Why lstack](#why-lstack)

---

## What it is

lstack is a portable ~/.claude environment for Claude Code. It adds persistent SQLite memory across sessions, loop detection, bash safety gates, auto-formatting, on-demand skills, and a custom statusline - all working through Claude Code's native hook system.

No runtime. No daemon. Dependencies: bash, git, and usable Python 3. Python can be `python3`, `python`, or `py -3` on Windows Git Bash.

---

## Install

One-liner:

    curl -fsSL https://raw.githubusercontent.com/puukis/lstack/main/install.sh | bash

Or manually:

    git clone https://github.com/puukis/lstack /tmp/lstack
    bash /tmp/lstack/install.sh

The installer detects your OS, verifies usable Python 3, generates the correct settings.json, initializes the memory database, and runs interactive onboarding. Existing ~/.claude setups are backed up with a timestamp before anything is written.

After install: restart Claude Code, then run `lstack init` in any project.

Windows: runs in Git Bash, not WSL. All hooks support native Windows Python through `py -3`; `python` and `python3` are not required if the launcher works. Use `/c/...` or `/d/...` paths in Git Bash, not `/mnt/c/...` WSL paths. If no usable Python is found, the installer stops with a fix message instead of installing broken hooks.

---

## Why lstack

| Feature                          | Vanilla CC | gstack | Superpowers | lstack |
|----------------------------------|------------|--------|-------------|--------|
| Persistent memory (SQLite)       | —          | —      | —           | yes    |
| Structured typed learnings       | —          | —      | —           | yes    |
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
| Intelligent sub-agent routing    | —          | —      | —           | yes    |
| No daemon / no runtime           | yes        | yes    | yes         | yes    |
| Semantic vector search           | —          | —      | —           | yes    |
| MCP server (local stdio)         | —          | —      | —           | yes    |
| Session end notifications        | —          | —      | —           | yes    |
| Session analytics                | —          | —      | —           | yes    |

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
| /freeze        | "only edit X", "freeze edits"                | restricts Edit/Write/MultiEdit to session paths                |
| /unfreeze      | "clear freeze", "remove edit lock"           | clears the current session edit boundary                       |
| /careful       | "be careful", prod/shared environment        | asks or denies before risky Bash commands                      |
| /guard         | "lock it down", "maximum safety"             | combines careful mode with an edit freeze                      |
| /architect     | new systems or large features                | ADRs and ARCHITECTURE.md before code                           |
| /parallel      | explicitly invoked                           | up to 3 sub-agents in isolated git worktrees                   |
| /learn         | explicitly invoked                           | stores typed, trust-aware structured learnings                 |
| /remember      | explicitly invoked                           | stores user-confirmed structured memory                        |
| /forget        | explicitly invoked                           | deletes or demotes structured learnings and observations       |
| /debrief       | explicitly invoked                           | end-of-session reflection written to disk in under 300 words   |
| /recall        | "what do you know", "do you remember"        | search structured learnings and legacy observations            |
| /analytics     | explicitly invoked                           | observation and structured learning analytics                  |
| /changelog     | explicitly invoked                           | generates CHANGELOG.md entry from git log since last tag       |
| /orchestrate   | Tier 2/3 tasks detected                      | Evaluates complexity, offers sub-agent dispatch with AskUserQuestion |
| /receipt       | explicitly invoked                           | manage Change Receipts: start, status, finalize, abandon, explain   |
| /passport      | explicitly invoked                           | show Repo Passport, context, overview, or run doctor                |
| /work          | explicitly invoked                           | structured work start: overview + context + receipt + firewall      |

---

## Hooks

| Hook                      | Event                  | What it enforces                                           |
|---------------------------|------------------------|------------------------------------------------------------|
| hooks/session-start.sh    | Session opens          | Injects memory and git context                             |
| hooks/pre-tool.sh         | Before any tool call   | Loop detection, safety gates, freeze/careful checks, memory lookup, re-read warnings |
| hooks/post-tool.sh        | After Write/Edit       | Auto-formats files, memory signal detector                 |
| hooks/pre-compact.sh      | Before compaction      | Saves handover summary via fresh subprocess                |
| hooks/stop.sh             | Session ends           | Runs project tests, stores session learnings in SQLite     |
| scripts/token-budget.sh   | Each prompt            | Warns at 60% context, alerts at 80%                        |

---

## Safety Modes

lstack has three per-session safety workflows layered on top of the existing global hard Bash gates.

### freeze

`freeze` restricts Claude Code edit tools to approved paths for the current session:

    lstack freeze src/auth
    lstack freeze --allow src/auth --allow tests/auth
    lstack freeze --show
    lstack unfreeze

When active, `hooks/pre-tool.sh` denies Edit, Write, and MultiEdit outside the allowed boundaries. Paths are normalized before comparison, so `src` does not match `src-old`, and repo-relative, absolute, Windows drive, and Git Bash `/c/...` paths are handled. Read, Glob, Grep, and Bash are not blocked by freeze by default.

Freeze state is stored per session under `~/.claude/logs/freeze-<session>.json`. The session id uses `CLAUDE_SESSION_ID` when available, otherwise a PPID-style fallback.

### careful

`careful` is opt-in Bash risk checking:

    lstack safety careful
    lstack safety strict
    lstack safety off
    lstack safety status

Careful mode returns a hook `ask` decision for risky Bash commands when Claude Code supports it. Strict mode returns `deny`. Existing global hard blocks still deny the most severe operations in every mode.

Detected risks include recursive deletes, destructive SQL, force pushes, hard resets, workspace-wide restore/checkout, git clean, kubectl delete, obvious production kubectl apply, destructive docker commands, recursive chmod/chown, device writes, process-kill patterns, and dependency-uninstall commands.

Smart safe exceptions allow repo-local generated-output cleanup such as:

    rm -rf node_modules .next dist build coverage .turbo .cache __pycache__ \
      .pytest_cache .ruff_cache target out tmp temp

The exception only applies when the target is confidently inside the current project or working directory. It never applies to `/`, `~`, `$HOME`, `/Users`, `/home`, `C:/Users`, drive roots, or uncertain variable/glob targets.

Override for opt-in careful/strict checks:

    LSTACK_CONFIRM_DESTRUCTIVE=1 <command>
    lstack safety allow-once <command-hash>

Global hard blocks remain hard blocks.

### guard

`guard` is the maximum safety workflow: careful mode plus freeze.

    lstack guard src/auth
    lstack guard --allow src/auth --allow tests/auth
    lstack guard --strict src/auth
    lstack guard --clear

By default guard enables `lstack safety careful` and freezes edits to the allowed paths. `--strict` uses strict Bash risk denial.

Status shows both layers:

    lstack safety status

The status output includes safety mode, freeze active state, allowed paths, session id, state file paths, creation times, and recent blocked/warned event count. Events are appended to `~/.claude/logs/safety-events.log` with command previews clamped and common secrets redacted.

Limitations: freeze and guard are accidental-damage guards, not a security sandbox. Bash can still mutate files unless caught by careful/strict or the global hard gates.

---

## Sub-Agent Architecture

lstack ships six specialist sub-agents in ~/.claude/agents/.
The main session orchestrates; workers handle scoped tasks in
isolation with their own context windows.

| Agent       | Model      | Purpose                                    |
|-------------|------------|--------------------------------------------|
| researcher  | Haiku 4.5  | Codebase exploration, pattern finding       |
| implementer | Sonnet 4.6 | Feature implementation, bug fixes          |
| reviewer    | Sonnet 4.6 | Code review, security audit                |
| tester      | Haiku 4.5  | Test writing                               |
| debugger    | Sonnet 4.6 | Root cause analysis                        |
| architect   | Sonnet 4.6 | System design, ADRs                        |

Model rationale: Haiku 4.5 delivers near-Sonnet 4 performance at
3.75x lower cost. Use it for search-and-summarize work. Sonnet 4.6
handles implementation and reasoning. The orchestrator model is
whatever model you're running in your main session.

Routing is automatic for Tier 3 tasks and user-prompted for Tier 2.
Tier 1 tasks (under 20 min, 1-2 files) never use sub-agents.

---

## Memory

lstack stores memory locally in SQLite at:

    ~/.claude/memory/lstack.db

There are two memory layers:

- **Legacy observations**: flat session notes stored in `observations`. Existing commands keep working: `lstack search`, `lstack memory stats`, `lstack memory prune`, and `lstack memory embed-all`.
- **Structured learnings**: typed, trust-aware records stored in `learnings`. These are durable facts, preferences, patterns, pitfalls, tool notes, and investigations with confidence, source, scope, tags, files, branch, commit, timestamps, optional embeddings, and append-only history.

Semantic vector search uses sqlite-vec + all-MiniLM-L6-v2 when available, falling back to FTS5 keyword search, then LIKE search. Embeddings are stored in the same SQLite database. There is no hosted service and no daemon.

Automatic injection points:

- **Session start**: injects a compact structured-learning block, then recent legacy observations. At most 5 structured learnings are injected.
- **Mid-session**: when Claude reads a file or runs a command, relevant structured learnings and observations can be retrieved. This is rate-limited.
- **Session end**: Stop hook runs the configured project test command and extracts only explicit `[LSTACK_LEARNING]` marker blocks from the final assistant message. No marker means nothing is stored.

Structured learning types:

    pattern, pitfall, preference, architecture, tool, operational, investigation

Sources:

    observed, user-stated, inferred, cross-model

Confidence and trust:

- Confidence is an integer from 1 to 10.
- `user-stated` defaults to confidence 10 and trusted true.
- `observed` defaults to confidence 8 and trusted false.
- `cross-model` defaults to confidence 8 and trusted false unless explicitly promoted.
- `inferred` defaults to confidence 5 and trusted false.
- Observed and inferred learnings decay by 1 point every 30 days.
- Untrusted cross-model learnings decay by 1 point every 60 days.
- Trusted user-stated learnings do not decay by default.
- Search can show original and effective confidence.

Safety model:

- Cross-project search requires `--cross-project`.
- Cross-project results are automatically trusted-only.
- Cross-project injection is disabled by default with `cross_project_learnings: false`.
- User-stated learnings are the only learnings allowed to propagate cross-project by default.
- Tool output, files, webpages, and PR text are never treated as user preferences.
- Unsafe instruction-like insights and unsafe keys are rejected.

Manual controls:

    lstack search "jwt auth"
    lstack memory stats
    lstack memory prune --days 90
    lstack memory embed-all   # backfill semantic embeddings
    lstack analytics          # observations per week, top tags

Structured learning examples:

    lstack learn add --type pitfall --key auth-token-expiry \
      --insight "JWT refresh fails when clock skew exceeds 30s" \
      --confidence 8 --source observed --file src/auth.ts

    lstack learn add --type preference --key no-comments-default \
      --insight "User prefers code without comments unless WHY is non-obvious" \
      --source user-stated --global

    lstack learn search "clock skew" --type pitfall
    lstack learn search "portable shell" --cross-project --trusted-only
    lstack learn list --type preference
    lstack learn show 123
    lstack learn promote --id 123
    lstack learn demote --id 123
    lstack learn forget --id 123
    lstack learn stats
    lstack learn prune --older-than-days 120 --confidence-below 3 --dry-run
    lstack learn embed-all
    lstack learn export > learnings.jsonl
    lstack learn import learnings.jsonl
    lstack learn migrate-observations --dry-run

From inside Claude Code, use `/learn` or `/remember` to store a structured learning, `/recall` to search learnings and observations, `/forget` to delete or demote memory, and `/analytics` to inspect memory health.

Stop hook learning extraction:

    [LSTACK_LEARNING]
    type: operational
    key: windows-git-bash-stop-hook-recursion
    insight: Running claude -p inside a Stop hook starts nested Claude sessions on Windows Git Bash and can recurse.
    confidence: 9
    source: observed
    [/LSTACK_LEARNING]

The Stop hook accepts up to 5 marker blocks. Allowed types are `pattern`, `pitfall`, `preference`, `architecture`, `tool`, `operational`, and `investigation`. Allowed sources are `observed`, `user-stated`, `inferred`, and `cross-model`. Keys must use lowercase letters, numbers, dots, hyphens, or underscores. Unsafe instruction-like insights are rejected.

Automatic LLM extraction from transcripts is disabled by default because calling `claude -p` from inside lifecycle hooks can start nested Claude Code sessions and recurse. The default extractor is deterministic and local: it reads `last_assistant_message`, validates explicit markers, and stores compact observations like `[type/key] insight` with tags `lstack-learning`, type, source, and key. Stop writes use no-embed mode for speed; run `lstack memory embed-all` later to backfill observation embeddings.

Config lives in `~/.claude/memory/lstack-config.json` and is optional. Safe defaults:

    {
      "learning_extract_llm": false,
      "learning_extract_markers": true,
      "learning_max_markers": 5,
      "learning_stop_no_embed": true
    }

Logs:

    ~/.claude/logs/sessions.log
    ~/.claude/logs/learn-extract.log

`sessions.log` records Stop start, cwd, transcript path, Python availability, test status, and learning summaries. `learn-extract.log` records marker validation and DB write details. Full hook JSON and transcripts are not dumped.

Privacy: memory stays local in `~/.claude/memory/lstack.db` unless you explicitly export or sync it.

---

## MCP Server

lstack exposes its memory as a local MCP server via stdio transport. Any tool with MCP support can query and store observations.

Enable by running `lstack settings` (registers automatically), or manually:

    claude mcp add lstack -- python3 ~/.claude/scripts/mcp_server.py

On Windows Git Bash with only the Python launcher:

    claude mcp add lstack -- py -3 ~/.claude/scripts/mcp_server.py

Or start interactively:

    lstack mcp

Tools exposed: `memory_search`, `memory_store`, `memory_stats`.

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
| lstack freeze PATH    | Restrict Edit/Write/MultiEdit to session paths   |
| lstack unfreeze       | Clear the current session freeze boundary        |
| lstack safety status  | Show safety mode and freeze boundary             |
| lstack safety careful | Ask before risky Bash commands this session      |
| lstack safety strict  | Deny risky Bash commands this session            |
| lstack safety off     | Disable opt-in safety checks this session        |
| lstack guard PATH     | Enable careful mode plus freeze boundary         |
| lstack dashboard      | Live display of parallel agent worktrees         |
| lstack clean          | Prune logs and dead loop state files             |
| lstack upgrade        | Pull latest lstack from git                      |
| lstack publish        | Package lstack for sharing (strips personal data)|
| lstack analytics      | Memory analytics: observations per week, top tags|
| lstack mcp            | Start lstack MCP server (stdio transport)        |
| lstack memory embed-all | Backfill semantic embeddings for all observations|
| lstack brain status | Show LBrain local trust brain status             |
| lstack brain passport | Show repo facts, commands, package manager, paths|
| lstack brain context | Export compact context for AI coding tools       |
| lstack brain decisions | Manage durable implementation decisions        |
| lstack brain capture | Record events and review memory candidates       |
| lstack learn add      | Add a typed structured learning                  |
| lstack learn search   | Search structured learnings                      |
| lstack learn list     | List structured learnings                        |
| lstack learn promote  | Mark a learning trusted after explicit request   |
| lstack learn demote   | Mark a learning untrusted                        |
| lstack learn prune    | Prune old, low-confidence, or superseded learnings|
| lstack learn export/import | Backup or restore structured learnings      |

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
    ├── skills/                    skill subdirectories (SKILL.md each)
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

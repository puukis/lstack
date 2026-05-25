# LBrain

LBrain is the local trust brain for AI coding. It helps lstack answer what kind of repo this is, which commands and package manager are expected, which platform rules matter, which failed attempts should not be repeated, and what compact context should be handed to Claude, Codex, or ChatGPT.

Distribution LBrain is a generic engine plus safe inactive templates. Project LBrain contains decisions for the current repo. User-global LBrain contains personal rules explicitly created by the user. Test fixtures are examples used only by tests.

## Features

Core features:

- Repo Passport
- Failed Attempt Memory
- Context Export
- Redaction basics
- `lstack brain status`
- `lstack brain doctor`

Capture and Decisions:

- Persistent Implementation Decisions
- Auto-Capture Events
- Memory Candidates
- Candidate promotion to decisions or failed attempts
- Decision checks
- Active decision context export
- Doctor checks for decisions and candidates

Also available:

- Automatic Learning
- Task Contracts
- Change Receipts

## Quick Start

```bash
lstack brain status
lstack brain passport
lstack brain attempts add \
  --action "Tried npm install in pnpm repo" \
  --command "npm install" \
  --error "Lockfile mismatch" \
  --why-failed "The repo uses pnpm-lock.yaml and should not mutate npm lockfiles." \
  --replacement "Use pnpm install only after user approval." \
  --retry-policy ask \
  --confidence 9
lstack brain context --for codex
lstack brain decisions check
lstack brain capture event \
  --type failed_command \
  --summary "python3 was not found in Windows Git Bash" \
  --command "python3 scripts/db.py stats" \
  --source "manual" \
  --confidence-delta 2
lstack brain capture candidates
lstack brain doctor
```

## Commands

```bash
lstack brain status
lstack brain doctor
lstack brain passport
lstack brain passport refresh
lstack brain passport --json
lstack brain passport --for claude
lstack brain passport --for codex
lstack brain attempts add
lstack brain attempts list
lstack brain attempts search QUERY
lstack brain decisions add
lstack brain decisions list
lstack brain decisions search QUERY
lstack brain decisions show KEY
lstack brain decisions check
lstack brain decisions disable KEY
lstack brain capture status
lstack brain capture event
lstack brain capture candidates
lstack brain capture approve ID
lstack brain capture reject ID
lstack brain capture explain ID
lstack brain capture promote ID
lstack brain context
lstack brain context --for claude
lstack brain context --for codex
lstack brain context --for chatgpt
lstack brain context --json
lstack brain context --explain
lstack brain context --debug
```

## Persistent Implementation Decisions

Implementation decisions are durable scoped memory. Project decisions apply only to the detected project id. User-global decisions apply across projects only when explicitly created with a user source. Template and test-fixture decisions are inactive and are not injected into normal context.

Active project decisions and explicit user-global decisions may be included in normal context exports for Claude and Codex. Disabled decisions are not injected, but remain visible in `list` and `show`.

Decision checks scan the configured `--applies-to` paths, including globs, for forbidden patterns and required helper patterns. Checks warn only. They do not block commands and they skip generated folders such as `node_modules`, `dist`, `build`, coverage output, and Python cache folders.

## Auto-Capture

Capture uses three stages:

1. Event - a compact redacted signal from a command, user correction, platform fact, diff, doctor check, or test result.
2. Candidate - a possible durable memory item.
3. Active memory - a promoted decision or failed attempt.

Pending candidates are not included in normal context. They appear in `lstack brain capture candidates`, `lstack brain context --explain`, `lstack brain context --debug`, and `lstack brain doctor`.

Capture is deterministic. It does not call Claude, Codex, ChatGPT, or any other AI. It does not store raw full command output.

## Templates

Templates are examples and starter patterns. They are not active rules until the user or project enables them. Normal context export ignores templates, template checks do not scan files, and templates do not produce warnings.

Safe generic template examples include:

- Use the detected package manager consistently.
- Do not edit generated folders unless explicitly asked.
- Ask before editing lockfiles.
- Do not store secrets.
- Prefer the detected shell and path style.
- In Windows Git Bash, use `/c/...` or `/d/...` paths, not `/mnt/c/...` paths.
- Ask before deleting files.
- Run detected tests after code changes when practical.

The lstack repository may have project-scoped decisions such as using the lstack runtime Python provider, avoiding recursive Claude calls in lifecycle hooks, and keeping `lbrain/` in install and publish packaging. Those are lstack project decisions, not distribution defaults for unrelated repos.

## Privacy And Redaction

LBrain stores Repo Passport and related data in the existing local SQLite database at `~/.claude/memory/lstack.db` unless `LSTACK_DB_PATH` is set. It does not require cloud services or embeddings.

Before storing failed attempts or exporting context, LBrain redacts common secret forms:

- Authorization bearer headers
- GitHub tokens
- npm tokens
- JWTs
- passwords
- API keys
- PEM private keys
- SSH private keys
- `.env` style secret assignments

LBrain stores redacted command previews, command fingerprints, compact evidence summaries, decisions, and candidates. It does not store raw full command output by default. Suspected secrets prevent automatic promotion.

## Cross-Platform Notes

LBrain supports Windows Git Bash, macOS, WSL, and Linux. Windows-specific lstack behavior targets Git Bash, not WSL. In Git Bash, use `/c/...` or `/d/...` paths, not `/mnt/c/...` paths. WSL is reported as Linux with `shell_mode=wsl`.

The CLI is Python-backed. On Windows Git Bash, `py -3` may be available even when `python` and `python3` are not. Lifecycle hooks must degrade if Python is unavailable and must not call `claude -p` by default.

## Examples

Show the Repo Passport:

```bash
lstack brain passport
```

Record a failed attempt:

```bash
lstack brain attempts add \
  --action "Tried npm install in pnpm repo" \
  --command "npm install" \
  --error "Lockfile mismatch" \
  --why-failed "The repo uses pnpm-lock.yaml and should not mutate npm lockfiles." \
  --replacement "Use pnpm install only after user approval." \
  --retry-policy ask \
  --confidence 8
```

Export compact context for Codex:

```bash
lstack brain context --for codex
```

Run diagnostics:

```bash
lstack brain doctor
```

Check active implementation decisions:

```bash
lstack brain decisions check
```

Review pending capture candidates:

```bash
lstack brain capture candidates
```

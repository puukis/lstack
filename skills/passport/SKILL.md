---
name: passport
description: Show or refresh Repo Passport and context — wraps lstack brain passport/context/overview CLI
allowed-tools: Bash
disable-model-invocation: false
---

# Passport — Repo Passport and context

## Activation
Invoked via `/passport`. Wraps `lstack brain passport`, `context`, `overview`, and `doctor` CLI.
The CLI is the source of truth. Never reimplement context selection here.

## Supported forms

```
/passport
/passport show
/passport refresh
/passport context
/passport overview
/passport doctor
/passport json
```

## Behavior by subcommand

### /passport  or  /passport show

Show compact Repo Passport facts for Claude:
```bash
lstack brain passport --for claude
```
If `--for claude` is unsupported by the installed CLI, fall back to:
```bash
lstack brain passport
```
Do not dump raw JSON by default. Show human-readable output.

### /passport refresh

Refresh the passport then display it:
```bash
lstack brain passport refresh
lstack brain passport --for claude
```
Fall back to `lstack brain passport` if `--for claude` is unsupported.

### /passport context

Export compact context via Context Governor:
```bash
lstack brain context --for claude
```
Do not reimplement context selection. Let the CLI decide what is relevant.

### /passport overview

Show Brain overview:
```bash
lstack brain overview
```

### /passport json

Show Brain overview as JSON (stable data API):
```bash
lstack brain overview --json
```
Display the raw JSON output. Do not parse or reformat it.

### /passport doctor

Run diagnostics:
```bash
lstack brain doctor
```
Report pass/warn/fail output honestly. Do not suppress warnings.

## Constraints

- Never reimplement context selection or passport logic in this skill.
- Never invoke Claude recursively or spawn subprocesses via AI CLI flags.
- Never store passport data in markdown files.
- The CLI is the source of truth for all repo facts.
- If a command fails, show the error and tell the user what to run manually.

---
name: work
description: Start structured AI coding work with Brain overview, Repo Passport, Context Governor, Change Receipts, and AI Mistake Firewall awareness
allowed-tools: Bash, Read, AskUserQuestion
disable-model-invocation: false
---

# Work — structured AI coding work

## Activation
Invoked via `/work`. Brings together Brain overview, Repo Passport, Context Governor,
Change Receipts, and AI Mistake Firewall before any code work begins.

## Supported forms

```
/work <task>
/work continue
/work status
/work context
```

## Behavior by subcommand

### /work <task>

Run this sequence before starting any work:

**A. Brain overview**
```bash
lstack brain overview
```
Show compact summary. Note any active Decisions, Failed Attempts, or warnings.

**B. Claude context**
```bash
lstack brain context --for claude
```
Show compact context. Note any active Task Contracts, protected files, or generated folders.

**C. Check current receipt**
```bash
lstack brain receipt status
```

**D. Receipt handling**

If no receipt is open:
```bash
lstack brain receipt start --title "<short title>" --goal "<full task>"
```
Derive a short title (≤60 chars) from the task. Preserve the user's full task as the goal.

If a receipt is already open, show it and use `AskUserQuestion` to ask:
- This task belongs to the open receipt — continue
- This is a new task — finalize the open receipt first
- This is a new task — abandon the open receipt first

Do not start another receipt silently.

**E. AI Mistake Firewall precheck**
```bash
lstack brain firewall status
```
If the task includes specific commands, files, or paths, check them:
```bash
lstack brain firewall check --command "<command>" --path "<path>" --changed-file "<file>"
```
Do not execute the checked command. Treat firewall warnings as guidance unless the user
explicitly requested strict mode.

**F. Work summary before starting**

Before proceeding with actual work, show a compact constraint summary:
- Platform path rule (from passport/context)
- Open receipt id
- Active Task Contract if any
- Protected files or deny-listed paths
- Generated folders to avoid editing
- Active Decisions
- Relevant Failed Attempts
- AI Mistake Firewall status

Then proceed with the requested work, keeping the open receipt in scope.

### /work continue

```bash
lstack brain overview
lstack brain receipt status
lstack brain context --for claude
```

If a receipt is open, continue working inside it.
If none is open, use `AskUserQuestion` to ask whether to start one.

### /work status

```bash
lstack brain overview
lstack brain receipt status
lstack brain doctor
```

Report status only. Do not start a receipt.

### /work context

```bash
lstack brain context --for claude
```

Optionally follow with:
```bash
lstack brain overview
```

Report context only. Do not start a receipt.

## Constraints

- Never bypass receipts: always check receipt status before work.
- Never hide firewall or doctor warnings.
- Never start a receipt when the user only asked for status or context.
- Never run tests until finalization or explicit user request.
- Never invoke Claude recursively or spawn subprocesses via AI CLI flags.
- Never run destructive or state-mutating git commands (reset, clean, restore, push, pull, commit).
- The CLI is the source of truth. Do not duplicate Brain storage logic.
- If a CLI command fails, show the error and tell the user what to run manually.

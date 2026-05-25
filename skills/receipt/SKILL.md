---
name: receipt
description: Manage Change Receipts from Claude Code — wraps lstack brain receipt CLI
allowed-tools: Bash, Read, AskUserQuestion
disable-model-invocation: false
---

# Receipt — manage Change Receipts

## Activation
Invoked via `/receipt`. Wraps `lstack brain receipt` CLI.
The CLI is the source of truth. Never duplicate receipt storage logic here.

## Supported forms

```
/receipt
/receipt help
/receipt start <task>
/receipt status
/receipt list
/receipt show <id>
/receipt finalize
/receipt finalize <summary>
/receipt abandon <reason>
/receipt explain
/receipt undo
/receipt record-test <command>
/receipt record-command <command>
```

## Behavior by subcommand

### /receipt  or  /receipt help

Run:
```bash
lstack brain receipt status
```
Show brief help listing the supported forms above. Do not create or finalize anything.

### /receipt start <task>

First check current state:
```bash
lstack brain receipt status
```

If no receipt is open, derive a short title (≤60 chars) and start one:
```bash
lstack brain receipt start --title "<short title>" --goal "<full task>"
```

If a receipt is already open, show it and use `AskUserQuestion` to ask:
- Continue the open receipt
- Finalize the open receipt first, then start new
- Abandon the open receipt first, then start new

Do not silently replace an open receipt.

### /receipt status

```bash
lstack brain receipt status
```

### /receipt list

```bash
lstack brain receipt list --limit 10
```

### /receipt show <id>

```bash
lstack brain receipt show <id>
```
`<id>` is a positional integer argument (not --id).

### /receipt finalize  or  /receipt finalize <summary>

First:
```bash
lstack brain receipt status
```

If no receipt is open, report that clearly.

If a receipt is open:
1. Look for a test command in `.claude/CLAUDE.md` under Build & Test.
2. If a test command is found, ask the user whether to run it before finalizing.
3. If the user approves, run the test. Record the result honestly:
   ```bash
   lstack brain receipt record-test --command "<cmd>" --result pass
   # or
   lstack brain receipt record-test --command "<cmd>" --result fail
   ```
4. If no test command is known, either ask for one or ask whether to finalize without recorded tests.
5. Finalize:
   ```bash
   lstack brain receipt finalize --summary "<summary>"
   ```
   If no summary was supplied, generate one from the open receipt goal/title.

Never claim tests passed unless they actually passed. Never invent test results.

### /receipt abandon <reason>

If reason is supplied:
```bash
lstack brain receipt abandon --reason "<reason>"
```
Note: `--reason` is required by the CLI; ask for it if missing.

If reason is missing, use `AskUserQuestion` to request one before proceeding.

### /receipt explain

```bash
lstack brain receipt explain
```

### /receipt undo

```bash
lstack brain receipt undo-hint
```
Print the suggested manual commands. Do not execute undo commands automatically.

### /receipt record-test <command>

Only run the command if it is clearly a test command or the user explicitly asked to run it.
Record pass/fail honestly after actually running it:
```bash
lstack brain receipt record-test --command "<command>" --result pass
# or
lstack brain receipt record-test --command "<command>" --result fail
```

### /receipt record-command <command>

Only record commands that were actually run this session. Record result honestly.
```bash
lstack brain receipt record-command --command "<command>" --result pass
# or
lstack brain receipt record-command --command "<command>" --result fail
```

## Constraints

- Never duplicate LBrain receipt storage logic in this skill.
- Never invoke Claude recursively or spawn subprocesses via AI CLI flags.
- Never run destructive or state-mutating git commands (reset, clean, restore, push, pull, commit).
- Never claim tests passed unless they actually passed.
- Never invent test results or receipt summaries.
- If the CLI returns an error, show it to the user and suggest what to run manually.
- The `--reason` flag is required by `lstack brain receipt abandon` — always supply it.
- `lstack brain receipt show` takes a positional integer, not `--id`.

---
name: careful
description: Enable opt-in warnings or denials for risky Bash commands in the current Claude Code session.
allowed-tools: Bash, AskUserQuestion
disable-model-invocation: false
---

# Careful

Use when the user says be careful, production mode, safety mode, shared environment, or asks to warn before destructive commands.

## Process

1. If the user explicitly asks for strict mode, run `lstack safety strict`.
2. Otherwise run `lstack safety careful`.
3. Run `lstack safety status` when useful to confirm the mode.
4. Explain the active behavior briefly.

## Modes

- `careful`: asks before risky Bash commands when hook ask is supported.
- `strict`: denies risky Bash commands.
- `off`: disables opt-in safety checks.

## Required Notes

- Existing global hard blocks remain active in every mode.
- Careful mode is not a shell sandbox.
- `LSTACK_CONFIRM_DESTRUCTIVE=1` or `lstack safety allow-once <hash>` can be used as an explicit override for opt-in careful/strict checks where appropriate. Global hard blocks still remain hard blocks.

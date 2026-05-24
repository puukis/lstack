---
name: guard
description: Enable maximum safety workflow by combining careful safety mode with a freeze edit boundary.
allowed-tools: Bash, AskUserQuestion
disable-model-invocation: false
---

# Guard

Use when the user says guard mode, lock it down, maximum safety, only touch a directory plus be careful, or similar.

## Process

1. If no path was supplied, ask which file or directory should remain editable.
2. Resolve the path from the current working directory with Bash.
3. Run `lstack guard <path>` or `lstack guard --allow <path> --allow <path2>`.
4. If the user asked for strict behavior, run `lstack guard --strict <path>`.
5. Confirm both protections.

## Required Notes

- Guard enables careful mode by default and activates freeze.
- Freeze restricts Edit, Write, and MultiEdit to the allowed paths.
- Careful mode asks before risky Bash commands when hook ask is supported.
- Bash can still mutate files. Guard is accidental-damage protection, not a security sandbox.
- Clear guard with `lstack guard --clear`.

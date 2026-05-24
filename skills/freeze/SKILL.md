---
name: freeze
description: Restrict Edit, Write, and MultiEdit to approved paths for the current Claude Code session.
allowed-tools: Bash, AskUserQuestion
disable-model-invocation: false
---

# Freeze

Use when the user says to only edit a path, freeze edits, restrict edits, or lock file changes to a directory.

## Process

1. If no path was supplied, ask which file or directory should be editable.
2. Resolve the path from the current working directory with Bash.
3. Run `lstack freeze <path>` or `lstack freeze --allow <path> --allow <path2>`.
4. Tell the user the boundary that is active.

## Required Notes

- Freeze applies to Edit, Write, and MultiEdit.
- Read, Glob, Grep, and Bash are not blocked by freeze by default.
- Bash can still mutate files. Freeze is an accidental-edit guard, not a security sandbox.
- To change the boundary, run `lstack unfreeze` or `lstack freeze <path>`.

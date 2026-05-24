---
name: unfreeze
description: Clear the current Claude Code session freeze boundary.
allowed-tools: Bash
disable-model-invocation: false
---

# Unfreeze

Use when the user asks to remove, clear, or disable the edit boundary.

## Process

1. Run `lstack unfreeze`.
2. Confirm that Edit, Write, and MultiEdit are no longer restricted by freeze.

## Required Notes

- This only clears the current session freeze state.
- It does not change global hard safety gates or careful/strict safety mode.

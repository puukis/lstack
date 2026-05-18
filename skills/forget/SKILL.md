---
name: forget
description: Delete observations from persistent memory — when user says forget, remove, or delete a memory
allowed-tools: Bash
disable-model-invocation: false
---

# Forget — delete observations from persistent memory

## Activation
Invoked via /forget. Use when the user says:
  "forget that", "remove that from memory", "delete that memory",
  "that's wrong, forget it", or similar.
Also invoke proactively when you realize a stored memory is incorrect.

## Process
1. Identify what to forget from the user's message.
   Extract 1-3 keywords that would match the observation.
2. Preview what will be deleted:
   Bash: python C:\Users\Leo\.claude\scripts\db.py search "[keywords]" --limit 5
   Show the results to the user and ask: "Delete these [N] observations? [y/N]"
3. Wait for confirmation. Do not delete without explicit yes.
4. On confirmation:
   Bash: python C:\Users\Leo\.claude\scripts\db.py forget "[keywords]"
5. Report: "Forgotten: [list of deleted observations]"
   If nothing matched: "No observations matched '[keywords]'. Nothing deleted."

## Constraints
- Always preview before deleting — never delete without showing what will go
- Always ask for confirmation before running db.py forget
- One forget call per /forget invocation — do not batch unrelated deletions
- If the user says "forget everything" or "clear all memory": refuse and explain
  that bulk deletion is not supported via this skill. Tell them to use:
  lstack memory prune --days 0  (with a warning that this deletes ALL observations)

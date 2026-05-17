---
name: build
description: Plan then implement with an explicit approval gate between phases — invoked via /build
allowed-tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep
disable-model-invocation: false
---

# Build — plan then implement, with approval gate between phases

## Activation
Invoked via /build. Use for any task that involves writing new code.

## Process
Phase 1 — Planning (runs /planner behavior):
  Ask 1-3 clarifying questions. Wait for answers.
  Produce a numbered task list with complexity estimates.
  Create TodoWrite entries for all tasks.
  Output: "Plan complete. Reply 'go' to start implementation, or give feedback."
  STOP. Wait for user response. Do not proceed until 'go' or equivalent is received.

Phase 2 — Implementation (runs /engineer behavior):
  Work through TodoWrite tasks in order.
  Mark each in_progress before starting, completed when done.
  Run tests after each logical unit of work, not just at the end.
  Report completion with a summary of what was built and test results.

## Constraints
- Never skip Phase 1.
- Never start Phase 2 without explicit user approval.
- Never batch multiple unrelated features into one /build run.

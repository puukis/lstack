---
name: parallel
description: Spawn isolated sub-agents across git worktrees for genuinely independent tasks
allowed-tools: Read, Write, Bash, Glob, Grep
disable-model-invocation: true
---

# Parallel — spawn isolated sub-agents across git worktrees

## Activation
Invoked via /parallel. Only use when tasks are genuinely independent.
Never use for tasks that share state or need sequential ordering.

## Persona
Orchestrator. Decomposes work into isolated units, delegates, collects results.

## Constraints
- Maximum 3 agents. Never spawn more.
- Each agent gets a task-specific minimal context file only (not global CLAUDE.md).
- Agents write output to .claude/parallel/[agent-id]/result.md only.
- Never pass large context between agents or to parent session.
- Clean up worktrees after results are collected.
- If any agent fails, report it — do not silently retry.

## Process
1. Ask: are these tasks truly independent? If not, refuse and explain why.
2. Create a worktree per task:
     git worktree add .claude/parallel/agent-[n] -b lstack-parallel-[n]
3. Write a minimal context file to each worktree:
     .claude/parallel/agent-[n]/TASK.md — task description + relevant file list only
4. Spawn each agent:
     cd .claude/parallel/agent-[n] && claude -p --allowedTools Read,Write,Bash \
       "$(cat TASK.md)" > result.md 2>&1 &
5. Wait for all agents to finish (poll result.md for completion marker).
6. Read all result.md files into parent session.
7. Summarize results and present them.
8. Clean up:
     git worktree remove .claude/parallel/agent-[n] --force
     git branch -D lstack-parallel-[n]

## Output format
Summary of all agent results, one section per agent.
Flag any agent that failed or produced no output.

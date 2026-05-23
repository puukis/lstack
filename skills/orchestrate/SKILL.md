---
name: orchestrate
description: >
  Intelligent task routing — evaluates complexity and asks the user
  whether to handle in the main session or dispatch to specialist
  sub-agents. Entry point for any medium or large task. Run this
  before /build or /engineer on anything non-trivial.
allowed-tools: Bash, Glob, Read, AskUserQuestion
disable-model-invocation: false
---

# Orchestrate — intelligent task routing

## Activation
Invoked via /orchestrate. Run before any medium or large task.
Auto-activates when a request is Tier 2 or Tier 3 per the routing
rules in CLAUDE.md. Never auto-activates for Tier 1 tasks.

## Process

### Step 1 — Evaluate complexity

Without reading any files, estimate the task tier:

TIER 1 (handle in main session):
  - Under 20 min, 1-2 files, single concern
  → Skip orchestration. Proceed directly.

TIER 2 (ask user):
  - 20-60 min, 3-8 files, 2-3 concerns
  → Continue to Step 2.

TIER 3 (recommend sub-agents):
  - Over 60 min, 9+ files, 4+ concerns, parallel workstreams
  → Continue to Step 2 with a recommendation.

### Step 2 — Ask the user

Use AskUserQuestion:

  AskUserQuestion({
    questions: [
      {
        question: "This looks like a [Tier 2/3] task. How should I approach it?",
        options: [
          "Main session — handle everything here (simpler, no overhead)",
          "Sub-agents — dispatch to specialists (better for large tasks)",
          "Show me the plan first, then I'll decide"
        ]
      }
    ]
  })

If the user selects "Show me the plan first":
  - Outline the task breakdown: what sub-agents would handle what
  - Show estimated token cost (number of workers × task size)
  - Then ask again with the two remaining options

### Step 3 — If main session chosen

Proceed using the existing /build or /engineer skill.
No sub-agents. Keep it simple.

### Step 4 — If sub-agents chosen

4a. Decompose the task into independent workstreams.
    Each workstream maps to one sub-agent. Use this mapping:

    Research/exploration  → researcher (Haiku — cheap, use first)
    Implementation        → implementer (Sonnet)
    Bug diagnosis         → debugger (Sonnet)
    Code review           → reviewer (Sonnet — run after implementer)
    Test writing          → tester (Haiku — run after implementer)
    System design         → architect (Sonnet — run before implementer)
    Documentation         → use main session (too context-dependent for sub-agent)

4b. Ask the user which model to use for the orchestrator (main session):

    AskUserQuestion({
      questions: [
        {
          question: "Which model should orchestrate this task?",
          options: [
            "Sonnet 4.6 — balanced, default (recommended)",
            "Opus 4.6 — most capable, higher cost",
            "Keep current session model"
          ]
        }
      ]
    })

    Note: worker models are pre-configured in the sub-agent YAML files.
    Researcher and tester use Haiku. Implementer, reviewer, debugger,
    architect use Sonnet. This is already optimal.

4c. State the dispatch plan clearly:
    "I will:
    1. [researcher] — scan [X] for [Y] (parallel)
    2. [architect] — design [Z] based on research output (sequential)
    3. [implementer] — implement [A] from the architecture (sequential)
    4. [reviewer] + [tester] — review and test in parallel (parallel)"

4d. Dispatch sub-agents in the described order.
    Parallel sub-agents: invoke simultaneously.
    Sequential sub-agents: wait for prior output before invoking.

4e. After all sub-agents complete, synthesize:
    - What each sub-agent produced
    - Any conflicts or issues between their outputs
    - What the main session still needs to do (usually: integrate, commit)
    - Whether the result needs human review before proceeding

### Step 5 — Store orchestration decision in memory

After the task completes, call /remember with:
"Used [N] sub-agents for [task type] — [outcome in 10 words]"
Scope: project.

This builds up a record of what orchestration patterns work for this
codebase, which injection surfaces at the start of future sessions.

## Constraints

- Never dispatch more than 3 parallel sub-agents at once.
- Never dispatch a sub-agent for a task under 20 minutes.
- Always ask the user before dispatching. No silent auto-dispatch.
- If a sub-agent fails or produces unexpected output, report it
  to the user before continuing. Do not silently retry.
- Never pass raw sub-agent output directly to the user.
  Synthesize and summarize.

## Output format

Step 1: "[TIER N detected] — [reason in one sentence]"
Step 2: AskUserQuestion (no text before it)
Step 4c: Numbered dispatch plan
Step 4e: Synthesis summary with file list of what changed

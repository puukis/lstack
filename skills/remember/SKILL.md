---
name: remember
description: Store a single observation in persistent memory via db.py — invoked via /remember
allowed-tools: Bash, AskUserQuestion
disable-model-invocation: false
---

# Remember — store an observation in persistent memory

## Activation
Invoked via /remember. Use when you discover something important mid-session
that should survive beyond this conversation.

## Process
1. Summarize the finding in one sentence (max 150 chars). Be specific.
   Good: "RSC async params must be awaited before destructuring in Next.js 15"
   Bad:  "there was a bug with params"

2. Extract 3-6 keywords as tags (comma-separated, no spaces).

3. Use the AskUserQuestion tool to ask the user which scope to save to.
   Call it with exactly one question:

   AskUserQuestion({
     questions: [{
       question: "Save this to project memory or global memory?",
       options: [
         "Project — this project only",
         "Global — inject in every project"
       ]
     }]
   })

   - If the user selects "Project": use git rev-parse --show-toplevel
     as the project path
   - If the user selects "Global": use the string "global" as the
     project value

4. Determine session_id:
   Bash: python3 -c "import os; print(os.getppid())"

5. Determine project path (based on scope from step 3):
   - If scope is project: run git rev-parse --show-toplevel 2>/dev/null || pwd
   - If scope is global: use the string "global" as the project value

6. Run:
   python3 ~/.claude/scripts/db.py observe \
     "[session_id]" "[project_or_global]" "[summary]" "[tag1,tag2,tag3]"

7. Confirm to the user:
   "Stored [global|project]: [summary]"

## Constraints
- One observation per /remember call. Do not batch multiple findings.
- Never store observations about trivial things (file exists, command ran, test passed).
- Store only reusable knowledge: bugs, gotchas, patterns, architectural decisions, project-specific quirks.
- Max 150 chars for summary. Truncate if needed — specificity beats completeness.

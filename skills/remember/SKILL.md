---
name: remember
description: Store a single observation in persistent memory via db.py — invoked via /remember
allowed-tools: Bash
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
2. Extract 3–6 keywords as tags (comma-separated, no spaces).
3. Determine session_id and project:
   - session_id: run `$PYTHON -c "import os; print(os.getppid())"`
   - project: run `git rev-parse --show-toplevel 2>/dev/null || pwd`
4. Run:
   ```
   $PYTHON ~/.claude/scripts/db.py observe \
     "[session_id]" "[project]" "[summary]" "[tag1,tag2,tag3]"
   ```
5. Confirm to the user: "Stored: [summary]"

## Constraints
- One observation per /remember call. Do not batch multiple findings.
- Never store observations about trivial things (file exists, command ran, test passed).
- Store only reusable knowledge: bugs, gotchas, patterns, architectural decisions, project-specific quirks.
- Max 150 chars for summary. Truncate if needed — specificity beats completeness.

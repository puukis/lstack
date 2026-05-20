---
name: recall
description: Search, browse, and manage persistent memory — find past observations, check what lstack knows, correct or delete entries.
allowed-tools: Bash
disable-model-invocation: false
---

# Recall — active memory management

## Activation
Invoked via /recall. Use when:
- You want to know what lstack remembers about a topic
- You suspect a stored memory is wrong or outdated
- You want to see recent observations for the current project
- Automatic injection did not surface something you expected

## Persona
A librarian with direct access to the memory database. Retrieves exactly
what is asked for. Does not summarize or editorialize. Reports what is
stored, not what it thinks is true.

## Commands

SEARCH — find observations matching a query:
    Bash: python $DB_PY search "[query]" --limit 5
    Where DB_PY = ~/.claude/scripts/db.py on macOS/Linux
    or the Windows path from os.sh $DB_PY variable.
    Present results as a numbered list with date and content.

RECENT — show the 5 most recent observations for this project:
    Bash: python $DB_PY session-start "recall-query" "[project]"
    Where project = git root or pwd.
    Present as a dated list.

STATS — show memory database summary:
    Bash: python $DB_PY stats
    Present the raw output.

CORRECT — fix a wrong observation:
    1. Search for the wrong observation: python $DB_PY search "[query]"
    2. Show it to the user and confirm it is the one to fix.
    3. Delete it: python $DB_PY forget "[query]"
    4. Store the corrected version: /remember

LIST BY TAG — find observations with a specific tag:
    Bash: python $DB_PY search "[tag]" --limit 10
    Tags are comma-separated keywords stored with each observation.

## Process
1. Ask what the user wants to do if not clear from context:
   - "Search for something specific?" → SEARCH
   - "What do you remember about this project?" → RECENT
   - "How much is stored?" → STATS
   - "Something stored is wrong" → CORRECT
2. Run the appropriate command.
3. Present results clearly. If nothing found, say so directly.
4. Offer the next logical action:
   - Empty results → "Nothing stored. Use /remember to save something."
   - Wrong entry → "Run /forget [keywords] to delete it."
   - Correct entry → "This is what I know. Injection will surface it next session."

## Constraints
- Never modify observations without user confirmation.
- Never invent observations that are not in the database.
- Never run db.py forget without showing what will be deleted first.
- If DB_PY path is unclear, run:
    Bash: python -c "import pathlib; print(str(pathlib.Path.home() / '.claude' / 'scripts' / 'db.py'))"
  to resolve it.

## Output format
Numbered list for search results:
  [1] 2026-05-17  prefer bun install over npm install — bun is faster
       tags: bun, npm, install

Plain text for stats output.
One confirmation line after any modification.

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

RECENT — show the 5 most recent observations for this project (and global):
    Bash: python $DB_PY session-start "recall-query" "[project]"
    Where project = git root or pwd.
    Output already includes [scope] labels — present as a dated list.

STATS — show memory database summary:
    Bash: python $DB_PY stats
    Present the raw output.

CORRECT — fix a wrong observation:
    1. Search for the wrong observation: python $DB_PY search "[query]"
    2. Show it to the user and confirm it is the one to fix.
    3. Delete it: python $DB_PY forget "[query]"
    4. Store the corrected version: /remember

EDIT — modify an existing observation in place:
    1. Search for the observation to edit:
           python3 ~/.claude/scripts/db.py search "[query]" --limit 5
       Results include an ID for each observation.
    2. Show results to the user and ask which one to edit.
       Use AskUserQuestion with the observations as options.
    3. Ask the user what to change using AskUserQuestion:
           AskUserQuestion({
             questions: [{
               question: "What do you want to edit?",
               options: [
                 "Content (the text)",
                 "Tags",
                 "Scope (project ↔ global)",
                 "Multiple fields"
               ]
             }]
           })
    4. For each field being edited, ask for the new value.
       For scope changes, use AskUserQuestion:
           AskUserQuestion({
             questions: [{
               question: "Change scope to:",
               options: [
                 "Project — this project only",
                 "Global — inject in every project"
               ]
             }]
           })
    5. Show a preview of what will change:
           Current: [old content / tags / scope]
           New:     [new content / tags / scope]
       Ask for confirmation before applying.
    6. Apply the edit:
           python3 ~/.claude/scripts/db.py edit [id] \
             --content "[new content]" \
             --tags "[new tags]" \
             --project "[new project or 'global']"
       Only pass flags for fields that actually changed.
    7. Confirm: "Updated observation [id]: [new content]"

LIST BY TAG — find observations with a specific tag:
    Bash: python $DB_PY search "[tag]" --limit 10
    Tags are comma-separated keywords stored with each observation.

## Process
1. Ask what the user wants to do if not clear from context:
   - "Search for something specific?" → SEARCH
   - "What do you remember about this project?" → RECENT
   - "How much is stored?" → STATS
   - "Something stored is wrong" → CORRECT
   - "Edit / update / change a memory" → EDIT
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
  [1] id=42  2026-05-17  [project]  prefer bun install over npm install — bun is faster
       tags: bun, npm, install
  [2] id=7   2026-05-17  [global]   SessionStart hook requires hookSpecificOutput wrapper
       tags: hook, session, wrapper

Plain text for stats output.
One confirmation line after any modification.

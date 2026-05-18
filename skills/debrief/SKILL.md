---
name: debrief
description: End-of-session structured reflection — what worked, what broke, what to do differently. Run before /exit.
allowed-tools: Read, Write, Bash, Glob
disable-model-invocation: false
---

# Debrief — structured end-of-session reflection

## Activation
Invoked via /debrief. Run at the end of any session longer than ~30 minutes,
or any session where something went wrong, took longer than expected, or
produced a non-obvious result.

Do NOT auto-activate. This is always an explicit choice.

## Persona
An honest engineer reviewing their own work without ego. Does not celebrate
wins or catastrophize failures. States facts. Identifies patterns. Produces
one concrete change for next time.

## Constraints
- Never praise the session ("great work", "solid progress").
- Never catastrophize failures ("this was a disaster").
- The Output section is written to disk, not just printed to chat.
- Keep it under 300 words total. Brevity is the point.
- The "Next session" section must contain exactly one actionable item,
  not a list.

## Process

1. Read the session context — what was attempted, what tools were called,
   what succeeded, what failed. Use existing context in the conversation;
   do not re-read files unless necessary.

2. Determine output path:
   - If inside a git repo: .claude/memory/debrief.md
   - Otherwise: ~/.claude/memory/debrief.md
   Overwrite if file already exists — only the latest debrief is kept.

3. Write the debrief file with this exact structure:

---
# Debrief — [ISO date]

## What was attempted
[1-3 sentences. What was the goal at the start of this session.]

## What worked
[Bullet list. Specific things that went well. Skip if nothing notable.]

## What did not work
[Bullet list. Specific failures, wrong assumptions, wasted time.
 If nothing failed, write "Nothing notable."]

## Root cause of the biggest failure
[One sentence. If nothing failed, write "N/A".]

## What to do differently next session
[One specific, actionable item. Not a list. Not vague ("be more careful").
 Something concrete: "Run /interrogate before touching any code on this task"
 or "Check if the Windows path issue applies before writing any hook".]

## Observations worth saving
[Any finding that meets the /remember criteria but wasn't saved mid-session.
 If already saved via /remember, write "None — already captured."]
---

4. After writing the file, offer to store any unsaved observations:
   "Debrief written. If 'Observations worth saving' has content, run /remember
   to store them before closing."

5. Print the file path only. Do not print the full debrief content to chat.

## Output format
File written to disk. One confirmation line in chat with the file path.

---
name: changelog
description: Generate a CHANGELOG.md entry from git log since last tag — invoked via /changelog
allowed-tools: Bash, Read, Write, AskUserQuestion
disable-model-invocation: false
---

# Changelog — generate changelog entry from git history

## Activation
Invoked via /changelog. Use before any release or when CHANGELOG.md
needs updating.

## Process

1. Find the last git tag:
   Bash: git describe --tags --abbrev=0 2>/dev/null || echo "none"

2. Get commits since that tag (or all commits if no tag):
   Bash: git log --oneline --no-merges [last-tag]..HEAD 2>/dev/null
   If no tag: git log --oneline --no-merges | head -30

3. Read the existing CHANGELOG.md to understand the format.

4. Categorize the commits into:
   Added / Changed / Fixed / Removed / Security
   Use the commit message as the source of truth.
   Ignore: chore, docs, style, test commits unless they are significant.
   Keep each item to one line, past tense, user-facing language.

5. Determine the version number:
   - If the user specified one, use it.
   - Otherwise, read the latest version from CHANGELOG.md and suggest
     the next patch version (e.g. 1.0.0 → 1.0.1).
   - Use AskUserQuestion to confirm the version:
     AskUserQuestion({
       questions: [{
         question: "Which version is this release?",
         header: "Version",
         multiSelect: false,
         options: [
           { label: "[suggested patch]", description: "Increment patch version" },
           { label: "[suggested minor]", description: "Increment minor version" },
           { label: "[suggested major]", description: "Increment major version" },
           { label: "I'll type it", description: "Provide a custom version string" }
         ]
       }]
     })

6. Write the new entry to CHANGELOG.md, inserting it after the
   ## [Unreleased] section (or at the top if none exists).
   Format:
       ## [X.Y.Z] - YYYY-MM-DD

       ### Added
       - ...

       ### Fixed
       - ...

7. Confirm: "CHANGELOG.md updated. Review it before tagging."

## Constraints
- Never invent changes not in git log.
- Never include internal refactoring or test changes unless significant.
- Never overwrite existing entries — only insert above them.
- Max 15 items total per entry. Summarize if more.

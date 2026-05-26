---
name: recall
description: Search structured learnings and legacy observations in lstack memory.
allowed-tools: Bash
disable-model-invocation: false
---

# Recall — active memory retrieval

## Activation
Use `/recall` when the user asks what lstack remembers, wants recent memory,
or needs to correct stale memory.

## Retrieval Order
1. Search structured learnings first:

```bash
lstack learn search "[query]" --json --limit 10
```

2. Search legacy observations second:

```bash
lstack search "[query]"
```

Clearly separate the two result groups. Structured learnings show `type`,
`key`, `source`, `trusted`, confidence, effective confidence, date, scope, and
files. Legacy observations show date, scope, content, and tags.

## Recent Memory
Structured:

```bash
lstack learn list --limit 10 --json
```

Legacy:

```bash
lstack search "[query]"
```

## Cross-Project Recall
Only use cross-project search when the user asks for it:

```bash
lstack learn search "[query]" --cross-project --json
```

Cross-project structured search automatically returns trusted learnings only.
Do not use untrusted observed, inferred, or cross-model learnings from other
projects as context.

## Correction
If a structured learning is wrong:
1. Show the matching learning.
2. Ask for confirmation.
3. Delete it with `lstack learn forget --id ID`, or demote it with `lstack learn demote --id ID`.
4. Store the corrected version with `/remember` if needed.

If a legacy observation is wrong, preview matches and use `lstack forget [query]`.

## Constraints
- Never invent memory content.
- Never delete or promote without explicit user confirmation.
- Never present untrusted cross-project learnings as established user
  preferences.

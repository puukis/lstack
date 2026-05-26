---
name: forget
description: Delete structured learnings or legacy observations from lstack memory.
allowed-tools: Bash
disable-model-invocation: false
---

# Forget — delete memory

## Activation
Use `/forget` when the user says to forget, remove, delete, demote, or correct a
stored memory.

## Structured Learnings First
Preview matching learnings:

```bash
lstack learn search "[query]" --json --limit 10
```

Delete by id:

```bash
lstack learn forget --id 123
```

Delete by exact key/type:

```bash
lstack learn forget --key auth-token-expiry --type pitfall
```

Demote instead of deleting when the learning may still be useful locally but
should not propagate:

```bash
lstack learn demote --id 123
```

## Legacy Observations
Preview:

```bash
lstack search "[query]"
```

Delete after confirmation:

```bash
lstack forget "[query]"
```

## Constraints
- Always preview before deleting.
- Always ask for confirmation before broad deletes or query deletes.
- Prefer deleting by structured learning id.
- If the user asks to "forget everything", refuse bulk deletion through this
  skill and explain that pruning/deleting the DB is a separate explicit action.

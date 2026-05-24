---
name: analytics
description: Show lstack memory analytics, including structured learning health.
allowed-tools: Bash
disable-model-invocation: false
---

# Analytics — memory health

## Activation
Use `/analytics` when the user asks for memory analytics, learning counts,
decay status, repeated keys, or scope breakdowns.

## Commands
Overall analytics:

```bash
python3 ~/.claude/scripts/db.py analytics
```

Structured learning stats only:

```bash
python3 ~/.claude/scripts/db.py learn-stats
```

Machine-readable structured stats:

```bash
python3 ~/.claude/scripts/db.py learn-stats --json
```

## Report
Include:
- learnings by type
- learnings by source
- decayed learnings below useful threshold
- most repeated keys
- trusted vs untrusted
- top project scopes
- legacy observation counts when relevant

Do not infer conclusions beyond what the DB reports.

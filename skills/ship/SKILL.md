---
name: ship
description: Pre-ship checklist that gates the release — runs 5 checks and blocks until all pass
allowed-tools: Read, Write, Bash, Glob, Grep
disable-model-invocation: true
---

# Ship — pre-ship checklist; blocks on failures

## Activation
Invoked via /ship. Active only for this task.

## Persona
A release engineer who treats every release as a production event. Does not
approve a ship until every item on the checklist is green. Reports all failures
before stopping — does not stop at the first failure.

## Constraints
- Never mark "ship ready" unless all 5 checklist items pass
- Never skip an item
- Never approve a partial ship ("good enough")
- Report all failures together, not one at a time

## Process
Run all 5 checks in order. Collect results. Report all at once.

1. **Tests** — run test command from CLAUDE.md; must pass 100%
2. **Debug code** — grep for console.log, debugger, print(), TODO, FIXME, breakpoint;
   report any found in non-test files
3. **Env vars** — grep for process.env / os.environ / getenv;
   confirm each is documented in README or .env.example
4. **CHANGELOG** — confirm CHANGELOG.md exists and has an entry for this change
5. **README** — confirm README accurately describes current behavior (no stale steps)

## Output format
**Ship checklist:**
- [✓/✗] Tests: [N passing / FAILED: summary]
- [✓/✗] Debug code: [none / found: file:line list]
- [✓/✗] Env vars: [all documented / undocumented: VAR_NAME list]
- [✓/✗] CHANGELOG: [entry present / missing]
- [✓/✗] README: [accurate / stale: what's wrong]

**Verdict:** SHIP READY / BLOCKED — [list of failures]

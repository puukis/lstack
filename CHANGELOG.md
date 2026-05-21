# Changelog

All notable changes to lstack are documented here.
Format follows Keep a Changelog. Versions follow Semantic Versioning.

## [Unreleased]

### Added
- Semantic vector search via sqlite-vec and all-MiniLM-L6-v2 (falls back to FTS5)
- Global vs project memory scoping in /remember skill
- lstack MCP server exposing memory as Claude Code tools (memory_search, memory_store, memory_stats)
- AskUserQuestion scope selection in /remember
- Observation editing in /recall and db.py edit subcommand
- Session end desktop notifications (macOS, Windows, Linux)
- Session analytics command (lstack analytics, db.py analytics)
- Debrief injection at session start (injects last debrief if under 7 days old)
- /recall skill: search, browse, and manage persistent memory
- Smarter mid-session injection using semantic query from file path + command context
- memory/MEMORY.md gitignored, template added for clean installs
- lstack memory embed-all: backfill semantic embeddings for existing observations
- /interrogate skill: Socratic one-question-at-a-time requirement clarification
- /blueprint skill: spec-file generator (.blueprint.md) before implementation
- /forget skill: delete matching observations from persistent memory
- Intent detection in CLAUDE.md: skills auto-activate from natural language
- install.sh: one-command installer with OS detection, backup, and onboarding
- lstack doctor: diagnose installation health
- lstack onboard: interactive first-run setup
- SQLite persistent memory (db.py) with FTS5 full-text search
- Mid-session memory injection via PreToolUse hook
- Session-end learning extraction via Stop hook
- Cross-platform support: macOS, Linux, Windows (Git Bash)
- statusline.py: native Windows Python statusline
- gen-settings.sh: OS-aware settings.json generator
- Skill restructure: all skills moved to skills/[name]/SKILL.md format
- CLAUDE.md: complete rewrite with identity, memory, skills, rules, hooks
- Context pruner: warns when Claude re-reads a file already in session context
- Token budget warnings at 60% and 80% context usage
- Git-aware context injection in SessionStart hook
- PreCompact handover summary via fresh claude -p subprocess
- Dashboard: live parallel agent worktree monitor

## [1.0.0] - 2026-05-17

Initial release.

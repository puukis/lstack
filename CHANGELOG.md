# Changelog

All notable changes to lstack are documented here.
Format follows Keep a Changelog. Versions follow Semantic Versioning.

## [Unreleased]

### Added
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

# Contributing to lstack

lstack is a personal environment first. Contributions are welcome when they improve the core experience without adding dependencies or complexity.

## What fits

- Bug fixes in hooks or scripts, especially cross-platform issues
- New skills that follow the existing SKILL.md structure
- Improvements to install.sh or the lstack CLI
- Documentation fixes and clarifications

## What does not fit

- Features that require a running daemon or background service
- Dependencies beyond bash, python3 stdlib, git, and jq
- Skills that duplicate existing ones with minor variations
- Changes that break macOS, Linux, or Windows Git Bash compatibility

## How to contribute

1. Fork the repo and clone your fork
2. Make your changes in a branch: `git checkout -b fix/description`
3. Test on your platform. All hooks must pass in Git Bash on Windows and native bash on macOS and Linux.
4. Run `lstack doctor` and confirm all checks pass
5. Open a pull request with a clear description of what changed and why

## Skill format

New skills must live at `skills/[name]/SKILL.md` and include valid YAML frontmatter with `name`, `description`, and `allowed-tools` fields. See any existing skill for reference.

## Commit messages

Use conventional commits: `feat`, `fix`, `refactor`, `chore`, `docs`.
No Co-Authored-By trailers.

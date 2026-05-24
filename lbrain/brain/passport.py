"""Repo Passport detection and rendering."""

import json
from pathlib import Path

from .db import dumps, iso_now, latest_passport_row, row_to_passport
from .platform import path_style_recommendation, platform_facts

SCRIPT_KEYS = ("test", "build", "lint", "typecheck", "dev", "start", "format")
LOCK_PRIORITY = ("pnpm", "yarn", "npm", "bun")
LOCKFILES = {
    "pnpm": ("pnpm-lock.yaml",),
    "yarn": ("yarn.lock",),
    "npm": ("package-lock.json",),
    "bun": ("bun.lock", "bun.lockb"),
}
IMPORTANT_FOLDERS = ("src", "app", "lib", "scripts", "hooks", "tests", "docs", "skills", "agents")
GENERATED_FOLDERS = (
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    ".turbo",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
)
PROTECTED_FILES = (
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "bun.lock",
    "bun.lockb",
    ".env",
    ".env.*",
    "settings.json",
    ".npmrc",
    ".yarnrc",
    ".yarnrc.yml",
    ".pnpmfile.cjs",
)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _package_manager_from_package_json(pkg):
    value = pkg.get("packageManager") if isinstance(pkg, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().split("@", 1)[0]


def _detect_lockfiles(root):
    found = {}
    for manager, names in LOCKFILES.items():
        present = [name for name in names if (root / name).exists()]
        if present:
            found[manager] = present
    return found


def detect_package_manager(root):
    pkg = _read_json(root / "package.json") if (root / "package.json").exists() else {}
    declared = _package_manager_from_package_json(pkg)
    lockfiles = _detect_lockfiles(root)
    conflicts = []
    selected = None
    source = "none"
    explanation = "No package manager detected."

    if declared:
        selected = declared
        source = "package.json packageManager"
        explanation = f"Using packageManager from package.json: {declared}."
        if lockfiles and declared not in lockfiles:
            conflicts.append(
                {
                    "type": "packageManager-lockfile-mismatch",
                    "declared": declared,
                    "lockfiles": sorted(lockfiles),
                }
            )
    elif lockfiles:
        selected = next((pm for pm in LOCK_PRIORITY if pm in lockfiles), sorted(lockfiles)[0])
        source = "lockfile"
        explanation = f"Using {selected} from lockfile priority pnpm > yarn > npm > bun."
        if len(lockfiles) > 1:
            conflicts.append(
                {
                    "type": "multiple-lockfiles",
                    "selected": selected,
                    "lockfiles": sorted(lockfiles),
                    "explanation": explanation,
                }
            )

    return {
        "package_manager": selected,
        "package_manager_source": source,
        "package_manager_explanation": explanation,
        "package_json_packageManager": pkg.get("packageManager") if isinstance(pkg, dict) else None,
        "lockfiles": lockfiles,
        "conflicts": conflicts,
        "package_json": pkg,
    }


def _script_command(pm, key):
    if not pm:
        pm = "npm"
    if key in ("test", "start"):
        return f"{pm} {key}"
    return f"{pm} run {key}"


def detect_passport(root, project):
    root = Path(root)
    pm = detect_package_manager(root)
    pkg = pm.pop("package_json")
    scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
    detected_scripts = {
        key: {"script": scripts[key], "command": _script_command(pm.get("package_manager"), key)}
        for key in SCRIPT_KEYS
        if key in scripts
    }

    stacks = []
    if (root / "package.json").exists():
        stacks.append("Node")
    if (root / "tsconfig.json").exists():
        stacks.append("TypeScript")
    if any((root / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py")):
        stacks.append("Python")
    if (root / "Cargo.toml").exists():
        stacks.append("Rust")
    if (root / "go.mod").exists():
        stacks.append("Go")
    if any(root.glob("hooks/*.sh")) or any(root.glob("scripts/*.sh")):
        stacks.append("shell scripts")

    important = [name for name in IMPORTANT_FOLDERS if (root / name).is_dir()]
    generated = [name for name in GENERATED_FOLDERS if (root / name).exists()]
    protected = [name for name in PROTECTED_FILES if list(root.glob(name))]
    facts = platform_facts()
    rules = {
        "platform": facts,
        "shell_rules": [
            path_style_recommendation(facts["os"], facts["shell_mode"]),
        ],
        "package_manager": pm.get("package_manager"),
    }
    paths = {
        "important_folders": important,
        "generated_folders": generated,
        "protected_files": protected,
        "root_name": project["name"],
    }
    commands = {
        **pm,
        "scripts": detected_scripts,
    }
    danger_zones = generated + protected
    return {
        "stack": stacks or ["unknown"],
        "commands": commands,
        "paths": paths,
        "rules": rules,
        "architecture_summary": None,
        "danger_zones": danger_zones,
        "manual_overrides": {},
        "confidence": 8 if stacks or pm.get("package_manager") else 4,
    }


def save_passport(con, project, passport):
    previous = row_to_passport(latest_passport_row(con, project["id"]))
    manual_overrides = previous.get("manual_overrides", {}) if previous else {}
    passport["manual_overrides"] = manual_overrides
    version = (previous.get("version", 0) if previous else 0) + 1
    now = iso_now()
    con.execute(
        """
        INSERT INTO brain_passports (
            project_id, version, stack_json, commands_json, paths_json, rules_json,
            architecture_summary, danger_zones_json, manual_overrides_json,
            detected_at, source, confidence, privacy_class, redaction_status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project["id"],
            version,
            dumps(passport["stack"]),
            dumps(passport["commands"]),
            dumps(passport["paths"]),
            dumps(passport["rules"]),
            passport.get("architecture_summary"),
            dumps(passport["danger_zones"]),
            dumps(manual_overrides),
            now,
            "detected",
            int(passport.get("confidence", 5)),
            "local-only",
            "clean",
            now,
            now,
        ),
    )
    con.execute(
        """
        DELETE FROM brain_passports
        WHERE project_id = ? AND id NOT IN (
            SELECT id FROM brain_passports WHERE project_id = ?
            ORDER BY version DESC LIMIT 5
        )
        """,
        (project["id"], project["id"]),
    )
    con.commit()
    return row_to_passport(latest_passport_row(con, project["id"]))


def get_or_refresh_passport(con, project, refresh=False):
    row = latest_passport_row(con, project["id"])
    if row and not refresh:
        return row_to_passport(row)
    detected = detect_passport(project["root"], project)
    return save_passport(con, project, detected)


def passport_summary(passport):
    commands = passport["commands"]
    scripts = commands.get("scripts", {})
    paths = passport["paths"]
    lines = [
        "LBrain Repo Passport",
        f"Stack: {', '.join(passport['stack'])}",
        f"Package manager: {commands.get('package_manager') or 'unknown'}",
    ]
    if commands.get("conflicts"):
        lines.append(f"Package manager conflicts: {len(commands['conflicts'])}")
    if scripts:
        lines.append("Commands:")
        for key in SCRIPT_KEYS:
            if key in scripts:
                lines.append(f"  {key}: {scripts[key]['command']}")
    if paths.get("important_folders"):
        lines.append("Important folders: " + ", ".join(paths["important_folders"]))
    if paths.get("generated_folders"):
        lines.append("Generated folders: " + ", ".join(paths["generated_folders"]))
    if paths.get("protected_files"):
        lines.append("Protected files: " + ", ".join(paths["protected_files"]))
    return "\n".join(lines)


def passport_context(passport, target="codex"):
    commands = passport["commands"]
    scripts = commands.get("scripts", {})
    paths = passport["paths"]
    prefix = {
        "claude": "Use these local repo facts before editing:",
        "codex": "Repo facts for this task:",
    }.get(target, "Repo context:")
    lines = [
        prefix,
        f"- Stack: {', '.join(passport['stack'])}",
        f"- Package manager: {commands.get('package_manager') or 'unknown'}",
    ]
    for key in SCRIPT_KEYS:
        if key in scripts:
            lines.append(f"- {key}: {scripts[key]['command']}")
    if paths.get("generated_folders"):
        lines.append("- Do not edit generated folders unless explicitly asked: " + ", ".join(paths["generated_folders"]))
    if paths.get("protected_files"):
        lines.append("- Treat as protected or ask first: " + ", ".join(paths["protected_files"]))
    for rule in passport["rules"].get("shell_rules", []):
        lines.append(f"- Shell rule: {rule}")
    return "\n".join(lines)

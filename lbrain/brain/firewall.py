"""AI Mistake Firewall for LBrain.

Checks planned actions against known decisions, failed attempts, protected
files, active contracts, and open receipts. Warning-only by default;
--strict-exit triggers non-zero exit on high-severity findings.

Never executes commands. Never calls Claude. Never mutates files.
"""

from .platform import platform_facts

# ------------------------------------------------------------------
# Public constants
# ------------------------------------------------------------------

SEVERITY_HIGH = "high"
SEVERITY_WARN = "warn"
SEVERITY_INFO = "info"

_SEVERITY_ORDER = {SEVERITY_INFO: 0, SEVERITY_WARN: 1, SEVERITY_HIGH: 2}

_GENERATED_FOLDERS = {
    ".git",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}

_PROTECTED_FILES = {
    "settings.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "bun.lock",
    "bun.lockb",
    ".env",
    ".npmrc",
    ".yarnrc",
    ".yarnrc.yml",
}

_HOOK_LIFECYCLE_PATHS = {
    "hooks/",
    "hooks\\",
    ".claude/hooks/",
    ".claude\\hooks\\",
}

_PYTHON_SCRIPT_DIRS = {"scripts/", "scripts\\", "lbrain/", "lbrain\\"}

# Number of built-in deterministic rules
RULE_COUNT = 14


# ------------------------------------------------------------------
# Warning model
# ------------------------------------------------------------------

def _warning(severity, source, key, message, evidence, suggested_action, strict_exit_block=False):
    return {
        "severity": severity,
        "source": source,
        "key": key,
        "message": message,
        "evidence": evidence,
        "suggested_action": suggested_action,
        "strict_exit_block": strict_exit_block,
    }


# ------------------------------------------------------------------
# Helper predicates
# ------------------------------------------------------------------

def _is_hook_path(paths):
    for p in (paths or []):
        p_str = str(p).replace("\\", "/")
        if "hook" in p_str.lower() or "hooks/" in p_str.lower():
            return True
    return False


def _is_python_script_path(paths):
    for p in (paths or []):
        p_str = str(p).replace("\\", "/")
        for prefix in ("scripts/", "lbrain/"):
            if prefix in p_str:
                return True
    return False


def _basename(path):
    return str(path).replace("\\", "/").rstrip("/").split("/")[-1]


def _parent_folder(path):
    parts = str(path).replace("\\", "/").rstrip("/").split("/")
    return parts[-2] if len(parts) >= 2 else ""


def _path_in_generated(path):
    p_str = str(path).replace("\\", "/")
    for folder in _GENERATED_FOLDERS:
        if f"/{folder}/" in p_str or p_str.startswith(f"{folder}/") or _basename(p_str) == folder:
            return True
    return False


def _command_preview(command, max_len=80):
    if not command:
        return ""
    s = str(command)
    return s[:max_len] + ("..." if len(s) > max_len else "")


# ------------------------------------------------------------------
# Individual rule checks
# ------------------------------------------------------------------

def _check_mnt_path(command, facts):
    """Command uses /mnt/c while shell is git-bash."""
    if not command:
        return None
    shell_mode = facts.get("shell_mode", "")
    if shell_mode == "git-bash" and "/mnt/" in str(command):
        preview = _command_preview(command)
        return _warning(
            SEVERITY_WARN, "platform", "git-bash-not-wsl",
            f"Command uses /mnt/ path while this project runs in Windows Git Bash.",
            f"Command preview: {preview}",
            "Use /c/... or /d/... paths instead of /mnt/c/...",
        )
    return None


def _check_claude_p_in_hook(command, paths, tool):
    """Lifecycle hooks must not call claude -p."""
    if not command:
        return None
    cmd = str(command)
    if "claude -p" not in cmd and "claude--p" not in cmd:
        return None
    is_hook = _is_hook_path(paths) or (tool and "hook" in str(tool).lower())
    sev = SEVERITY_HIGH if is_hook else SEVERITY_WARN
    block = is_hook
    return _warning(
        sev, "decision", "no-claude-in-hooks",
        "Command calls claude -p which must not be used in lifecycle hooks.",
        f"Command contains: claude -p",
        "Remove claude -p from hooks. Hooks must not start nested Claude sessions.",
        strict_exit_block=block,
    )


def _check_direct_python_in_hook_script(command, paths):
    """Direct python/python3 in hook or script context when lstack runtime should be used."""
    if not command:
        return None
    cmd = str(command).strip()
    is_hook = _is_hook_path(paths)
    is_script = _is_python_script_path(paths)
    if not (is_hook or is_script):
        return None
    import re
    if re.match(r"^python3?\s", cmd) or re.search(r"[;&|]\s*python3?\s", cmd):
        return _warning(
            SEVERITY_WARN, "decision", "runtime-python-provider",
            "Command uses direct python/python3 in a hook or script context.",
            f"Command starts with: {cmd.split()[0]}",
            "Use the lstack runtime Python provider or run_python helper instead of direct python/python3.",
        )
    return None


def _check_co_authored_by(command):
    """Co-Authored-By must not appear in git commit messages."""
    if not command:
        return None
    if "Co-Authored-By" in str(command) or "co-authored-by" in str(command).lower():
        return _warning(
            SEVERITY_WARN, "decision", "no-coauthored-by-commits",
            "Git commit command includes Co-Authored-By attribution.",
            "Command contains: Co-Authored-By",
            "Remove Co-Authored-By from commit messages.",
        )
    return None


def _check_similar_to_failed_attempts(command, attempts):
    """Warn if command closely matches a high-confidence failed attempt."""
    if not command or not attempts:
        return None
    import re
    cmd_normalized = " ".join(str(command).strip().split()).lower()
    for attempt in attempts:
        if attempt.get("confidence", 0) < 7:
            continue
        if attempt.get("retry_policy") not in ("never", "ask", "after-change"):
            continue
        stored_cmd = str(attempt.get("command_redacted") or attempt.get("attempted_action") or "").lower()
        if not stored_cmd:
            continue
        # Simple token overlap heuristic
        cmd_tokens = set(re.split(r"\s+", cmd_normalized))
        stored_tokens = set(re.split(r"\s+", stored_cmd))
        overlap = cmd_tokens & stored_tokens - {"", "-", "--"}
        if len(overlap) >= 3 and len(overlap) / max(len(stored_tokens), 1) >= 0.5:
            action_preview = (attempt.get("attempted_action") or "")[:60]
            return _warning(
                SEVERITY_WARN, "failed_attempt", "similar-to-failed-attempt",
                f"Command resembles a recorded failed attempt.",
                f"Similar to: {action_preview}",
                attempt.get("replacement_approach") or "Check Failed Attempt Memory before retrying.",
            )
    return None


def _check_protected_file_edit(changed_files):
    """Editing a protected file."""
    warnings = []
    for f in (changed_files or []):
        name = _basename(f)
        if name in _PROTECTED_FILES:
            warnings.append(_warning(
                SEVERITY_WARN, "passport", "protected-file-edit",
                f"Editing a protected file: {name}",
                f"File: {name}",
                f"Be careful editing {name}. It is a protected configuration file.",
            ))
    return warnings


def _check_generated_folder_edit(changed_files):
    """Editing inside a generated/cached folder."""
    warnings = []
    for f in (changed_files or []):
        if _path_in_generated(f):
            folder = _basename(f) if _path_in_generated(f) else ""
            warnings.append(_warning(
                SEVERITY_WARN, "passport", "generated-folder-edit",
                f"Editing inside a generated or cached folder.",
                f"Path: {str(f)[:80]}",
                "Generated folders should not be edited directly. They are regenerated automatically.",
            ))
    return warnings


def _check_contract_patterns(changed_files, contract):
    """Changed files vs. active contract allow/deny patterns."""
    if not contract or not changed_files:
        return []
    import fnmatch
    warnings = []
    allow_patterns = contract.get("allowed_files") or []
    deny_patterns = contract.get("forbidden_files") or []

    for f in changed_files:
        f_str = str(f).replace("\\", "/")
        name = _basename(f_str)
        # Check deny first
        for pat in deny_patterns:
            if fnmatch.fnmatch(f_str, pat) or fnmatch.fnmatch(name, pat):
                warnings.append(_warning(
                    SEVERITY_HIGH, "contract", "contract-deny-pattern",
                    f"Changed file matches active contract deny pattern: {pat}",
                    f"File: {name}, Pattern: {pat}",
                    "This file is forbidden by the active Task Contract.",
                    strict_exit_block=True,
                ))
                break
        # Check allow (only if allow_patterns are specified)
        if allow_patterns:
            allowed = any(
                fnmatch.fnmatch(f_str, pat) or fnmatch.fnmatch(name, pat)
                for pat in allow_patterns
            )
            if not allowed:
                warnings.append(_warning(
                    SEVERITY_WARN, "contract", "contract-allow-pattern",
                    f"Changed file is outside active contract allowed scope.",
                    f"File: {name}",
                    "Check that this file is within the Task Contract scope.",
                ))
    return warnings


def _check_receipt_tests(receipt):
    """Warn if open receipt has changed files but no recorded tests."""
    if not receipt:
        return []
    warnings = []
    changed_count = len(receipt.get("files_changed") or [])
    tests_count = len(receipt.get("tests") or [])
    if changed_count > 0 and tests_count == 0:
        warnings.append(_warning(
            SEVERITY_WARN, "receipt", "receipt-no-tests",
            "Open Change Receipt has recorded file changes but no tests.",
            f"Changed files: {changed_count}, Tests recorded: 0",
            "Record at least one test before finalizing: lstack brain receipt record-test --command '...'",
        ))
    return warnings


def _check_no_open_receipt(changed_files, receipt):
    """Warn if risky edits are happening without an open receipt."""
    if receipt:
        return []
    if not changed_files:
        return []
    risky = [
        f for f in changed_files
        if not _path_in_generated(f) and _basename(f) not in _PROTECTED_FILES
    ]
    if len(risky) >= 2:
        return [_warning(
            SEVERITY_INFO, "receipt", "no-open-receipt",
            f"Editing {len(risky)} file(s) without an open Change Receipt.",
            f"Files: {', '.join(str(f)[:30] for f in risky[:3])}{'...' if len(risky) > 3 else ''}",
            "Consider starting a receipt to track this work: lstack brain receipt start --title '...'",
        )]
    return []


def _check_hook_edit_without_tests(changed_files, receipt):
    """Editing hooks without any tests recorded."""
    hook_edits = [
        f for f in (changed_files or [])
        if _is_hook_path([f])
    ]
    if not hook_edits:
        return []
    tests_count = len((receipt or {}).get("tests") or []) if receipt else 0
    if tests_count == 0:
        return [_warning(
            SEVERITY_WARN, "receipt", "hook-edit-no-tests",
            f"Editing hook file(s) without any recorded tests.",
            f"Hook files: {', '.join(_basename(f) for f in hook_edits[:3])}",
            "Record tests before editing hooks: lstack brain receipt record-test --command '...'",
        )]
    return []


def _check_claude_p_in_hook_path(changed_files):
    """Editing a lifecycle hook that may introduce claude -p."""
    warnings = []
    for f in (changed_files or []):
        if _is_hook_path([f]):
            warnings.append(_warning(
                SEVERITY_WARN, "decision", "hook-claude-p-risk",
                f"Editing lifecycle hook: {_basename(f)}. Ensure it does not call claude -p.",
                f"File: {_basename(f)}",
                "Lifecycle hooks must not call claude -p. Hooks must exit 0 and be fail-open.",
            ))
    return warnings


# ------------------------------------------------------------------
# Safe DB accessors
# ------------------------------------------------------------------

def _safe_get_active_contract(con, project_id):
    try:
        from .contracts import get_active_contract
        return get_active_contract(con, project_id)
    except Exception:
        return None


def _safe_get_open_receipt(con, project_id):
    try:
        from .receipts import get_open_receipt
        return get_open_receipt(con, project_id)
    except Exception:
        return None


def _safe_list_attempts(con, project_id, limit=20):
    try:
        from .attempts import list_attempts
        return list_attempts(con, project_id, limit=limit)
    except Exception:
        return []


def _safe_active_decisions(con, project_id):
    try:
        from .decisions import list_decisions
        return list_decisions(con, project_id, status="active", limit=50)
    except Exception:
        return []


def _safe_passport(con, project_id):
    try:
        from .db import latest_passport_row, row_to_passport
        row = latest_passport_row(con, project_id)
        return row_to_passport(row)
    except Exception:
        return None


# ------------------------------------------------------------------
# Main check function
# ------------------------------------------------------------------

def run_firewall_check(
    command=None,
    paths=None,
    changed_files=None,
    tool=None,
    con=None,
    project=None,
    facts=None,
):
    """Run all firewall checks and return a FirewallResult dict.

    Never executes the command. Never calls Claude. Never mutates state.
    """
    if facts is None:
        facts = platform_facts()

    warnings = []

    # Load data from DB if available
    contract = None
    receipt = None
    attempts = []
    if con is not None and project is not None:
        pid = project["id"]
        contract = _safe_get_active_contract(con, pid)
        receipt = _safe_get_open_receipt(con, pid)
        attempts = _safe_list_attempts(con, pid, limit=30)

    # --- Command-level checks ---
    w = _check_mnt_path(command, facts)
    if w:
        warnings.append(w)

    w = _check_claude_p_in_hook(command, paths, tool)
    if w:
        warnings.append(w)

    w = _check_direct_python_in_hook_script(command, paths)
    if w:
        warnings.append(w)

    w = _check_co_authored_by(command)
    if w:
        warnings.append(w)

    w = _check_similar_to_failed_attempts(command, attempts)
    if w:
        warnings.append(w)

    # --- Path-level checks ---
    warnings.extend(_check_protected_file_edit(changed_files))
    warnings.extend(_check_generated_folder_edit(changed_files))
    warnings.extend(_check_claude_p_in_hook_path(changed_files))
    warnings.extend(_check_hook_edit_without_tests(changed_files, receipt))

    # --- Contract checks ---
    warnings.extend(_check_contract_patterns(changed_files, contract))

    # --- Receipt checks ---
    warnings.extend(_check_receipt_tests(receipt))
    warnings.extend(_check_no_open_receipt(changed_files, receipt))

    # Determine overall status
    if any(w["severity"] == SEVERITY_HIGH for w in warnings):
        status = "high"
    elif any(w["severity"] == SEVERITY_WARN for w in warnings):
        status = "warn"
    elif warnings:
        status = "info"
    else:
        status = "pass"

    return {
        "status": status,
        "warning_count": len(warnings),
        "warnings": warnings,
        "checks_run": RULE_COUNT,
    }


# ------------------------------------------------------------------
# Status and explain
# ------------------------------------------------------------------

def firewall_status(con=None, project=None):
    """Return a status summary dict for `lstack brain firewall status`."""
    attempts_count = 0
    active_decisions_count = 0
    if con is not None and project is not None:
        pid = project["id"]
        attempts = _safe_list_attempts(con, pid, limit=1000)
        attempts_count = len([
            a for a in attempts
            if a.get("confidence", 0) >= 7
            and a.get("retry_policy") in ("never", "ask", "after-change")
        ])
        active_decisions_count = len(_safe_active_decisions(con, pid))

    return {
        "available": True,
        "rule_count": RULE_COUNT,
        "active_decisions_count": active_decisions_count,
        "failed_attempts_count": attempts_count,
        "protected_patterns_count": len(_PROTECTED_FILES),
        "generated_folders_count": len(_GENERATED_FOLDERS),
        "recent_warnings_count": 0,
    }


def firewall_explain(con=None, project=None):
    """Return an explanation of active firewall rules and sources."""
    active_decisions = []
    if con is not None and project is not None:
        active_decisions = _safe_active_decisions(con, project["id"])
    decision_summaries = [
        {"key": d.get("key"), "title": d.get("title")}
        for d in active_decisions[:10]
    ]
    return {
        "rule_count": RULE_COUNT,
        "sources": [
            {
                "name": "platform",
                "description": "Checks shell mode and path conventions (Git Bash vs WSL).",
            },
            {
                "name": "decisions",
                "description": (
                    "Checks active implementation decisions including: "
                    "Git Bash path rules, Python provider policy, "
                    "hook recursion guard, commit attribution policy."
                ),
            },
            {
                "name": "failed_attempt_memory",
                "description": "Warns when a command resembles a high-confidence past failure.",
            },
            {
                "name": "repo_passport",
                "description": "Checks protected files and generated folders.",
            },
            {
                "name": "task_contracts",
                "description": "Checks changed files against active Task Contract allow/deny patterns.",
            },
            {
                "name": "change_receipts",
                "description": (
                    "Warns on risky edits without an open receipt, "
                    "and receipts with no recorded tests."
                ),
            },
        ],
        "active_decisions": decision_summaries,
        "rules": [
            {
                "key": "git-bash-not-wsl",
                "source": "platform",
                "severity": "warn",
                "description": "Warns when a command uses /mnt/ paths while running in Windows Git Bash.",
            },
            {
                "key": "no-claude-in-hooks",
                "source": "decision",
                "severity": "high",
                "description": "Warns when a lifecycle hook command calls claude -p.",
            },
            {
                "key": "runtime-python-provider",
                "source": "decision",
                "severity": "warn",
                "description": "Warns when direct python/python3 is used in a hook or script context.",
            },
            {
                "key": "no-coauthored-by-commits",
                "source": "decision",
                "severity": "warn",
                "description": "Warns when a git commit command includes Co-Authored-By attribution.",
            },
            {
                "key": "similar-to-failed-attempt",
                "source": "failed_attempt",
                "severity": "warn",
                "description": "Warns when a command closely resembles a recorded failed attempt.",
            },
            {
                "key": "protected-file-edit",
                "source": "passport",
                "severity": "warn",
                "description": "Warns when editing a protected configuration file such as settings.json.",
            },
            {
                "key": "generated-folder-edit",
                "source": "passport",
                "severity": "warn",
                "description": "Warns when editing inside a generated or cached folder.",
            },
            {
                "key": "hook-claude-p-risk",
                "source": "decision",
                "severity": "warn",
                "description": "Warns when editing a lifecycle hook file.",
            },
            {
                "key": "hook-edit-no-tests",
                "source": "receipt",
                "severity": "warn",
                "description": "Warns when editing hook files without any recorded tests.",
            },
            {
                "key": "contract-deny-pattern",
                "source": "contract",
                "severity": "high",
                "description": "Warns when a changed file matches an active Task Contract deny pattern.",
            },
            {
                "key": "contract-allow-pattern",
                "source": "contract",
                "severity": "warn",
                "description": "Warns when a changed file is outside the Task Contract allowed scope.",
            },
            {
                "key": "receipt-no-tests",
                "source": "receipt",
                "severity": "warn",
                "description": "Warns when an open Change Receipt has changed files but no recorded tests.",
            },
            {
                "key": "no-open-receipt",
                "source": "receipt",
                "severity": "info",
                "description": "Notes when multiple files are being changed without an open receipt.",
            },
            {
                "key": "similar-to-failed-attempt",
                "source": "failed_attempt",
                "severity": "warn",
                "description": "Warns when a command closely resembles a high-confidence past failure.",
            },
        ],
    }


# ------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------

def render_firewall_check(result, verbose=False):
    lines = ["AI Mistake Firewall"]
    if not result["warnings"]:
        lines.append("PASS No warnings.")
        return "\n".join(lines)
    for w in result["warnings"]:
        sev = w["severity"].upper()
        key = w.get("key") or ""
        msg = w["message"]
        source = w.get("source") or ""
        lines.append(f"{sev} {source}.{key}: {msg}")
        if verbose and w.get("suggested_action"):
            lines.append(f"  Suggestion: {w['suggested_action']}")
    return "\n".join(lines)


def render_firewall_status(status_data):
    lines = [
        "AI Mistake Firewall",
        f"Available: {'yes' if status_data['available'] else 'no'}",
        f"Built-in rules: {status_data['rule_count']}",
        f"Active decisions: {status_data['active_decisions_count']}",
        f"High-confidence failed attempts: {status_data['failed_attempts_count']}",
        f"Protected files: {status_data['protected_patterns_count']}",
        f"Generated folders: {status_data['generated_folders_count']}",
    ]
    return "\n".join(lines)

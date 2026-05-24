"""Task contracts for LBrain."""

import fnmatch
import hashlib
import re
from pathlib import Path

from .db import dumps, iso_now, loads
from .platform import normalize_path
from .redaction import combine_status, redact_text

CONTRACT_STATUSES = {"draft", "active", "violated", "completed", "closed", "expired"}
CONTRACT_MODES = {"off", "warn", "strict"}
INACTIVE_STATUSES = {"completed", "closed", "expired"}

GENERATED_FOLDERS = {
    ".git", ".next", ".pytest_cache", ".ruff_cache", ".turbo",
    "__pycache__", "build", "coverage", "dist", "node_modules",
}


def _clamp_confidence(value, default=8):
    try:
        v = int(value)
    except Exception:
        return default
    return max(1, min(10, v))


def _redact_list(values):
    items = []
    statuses = []
    for v in values or []:
        t, s = redact_text(str(v), max_length=500)
        if t:
            items.append(t)
        statuses.append(s)
    return items, (combine_status(*statuses) if statuses else "clean")


def _command_fingerprint(cmd):
    redacted, _ = redact_text(str(cmd or ""), max_length=300)
    return hashlib.sha256(redacted.encode()).hexdigest()[:16]


def normalize_input_path(path_str, project_root=None):
    """Convert any path form to a project-relative posix string.

    Handles: C:\\path, C:/path, /c/path, /d/Work Space/path, relative paths.
    Returns a relative posix path when possible, else a normalized absolute one.
    """
    if not path_str:
        return None
    raw = str(path_str).strip()
    normalized = normalize_path(raw)
    if project_root:
        try:
            root = Path(normalize_path(str(project_root)))
            p = Path(normalized)
            rel = p.relative_to(root)
            return rel.as_posix()
        except (ValueError, TypeError):
            pass
    p = Path(normalized)
    if not p.is_absolute():
        return normalized.replace("\\", "/").lstrip("./") or normalized.replace("\\", "/")
    return normalized


def _match_pattern(path_rel, pattern):
    """Match a project-relative posix path against a glob pattern."""
    if not path_rel or not pattern:
        return False
    pattern = pattern.replace("\\", "/").strip()
    path_rel = path_rel.replace("\\", "/").strip()
    if path_rel == pattern:
        return True
    if fnmatch.fnmatch(path_rel, pattern):
        return True
    return False


def _check_path(path_str, allowed_files, forbidden_files, project_root=None):
    """Return (decision, reason) for a path."""
    if not path_str:
        return "allow", "no path provided"
    rel = normalize_input_path(path_str, project_root) or path_str

    for pattern in forbidden_files or []:
        if _match_pattern(rel, pattern):
            return "deny", f"path matches forbidden pattern: {pattern}"

    if allowed_files:
        for pattern in allowed_files:
            if _match_pattern(rel, pattern):
                return "allow", f"path matches allowed pattern: {pattern}"
        return "deny", "path not in allowed files list"

    return "allow", "no file restrictions"


def _check_command(cmd, allowed_commands, forbidden_commands):
    """Return (decision, reason) for a command."""
    if not cmd:
        return "allow", "no command provided"
    redacted, _ = redact_text(cmd, max_length=300)

    for pattern in forbidden_commands or []:
        if not pattern:
            continue
        if fnmatch.fnmatch(redacted, pattern) or pattern in redacted:
            return "deny", f"command matches forbidden pattern: {pattern}"

    if allowed_commands:
        for pattern in allowed_commands:
            if not pattern:
                continue
            if fnmatch.fnmatch(redacted, pattern) or pattern in redacted:
                return "allow", f"command matches allowed pattern: {pattern}"
        return "warn", "command not in allowed commands list"

    return "allow", "no command restrictions"


def contract_row_to_dict(row):
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "session_id": row["session_id"],
        "title": row["title"],
        "task_goal": row["task_goal"],
        "mode": row["mode"],
        "allowed_files": loads(row["allowed_files_json"], []),
        "forbidden_files": loads(row["forbidden_files_json"], []),
        "allowed_commands": loads(row["allowed_commands_json"], []),
        "forbidden_commands": loads(row["forbidden_commands_json"], []),
        "max_files_changed": row["max_files_changed"],
        "max_lines_changed": row["max_lines_changed"],
        "required_tests": loads(row["required_tests_json"], []),
        "recorded_tests": loads(row["recorded_tests_json"], []),
        "stop_conditions": loads(row["stop_conditions_json"], []),
        "review_checklist": loads(row["review_checklist_json"], []),
        "notes": row["notes"],
        "status": row["status"],
        "violation_count": row["violation_count"],
        "created_by": row["created_by"],
        "source": row["source"],
        "confidence": row["confidence"],
        "privacy_class": row["privacy_class"],
        "redaction_status": row["redaction_status"],
        "started_at": row["started_at"],
        "closed_at": row["closed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _record_event(
    con, contract_id, project_id, event_type, decision, reason,
    session_id=None, tool_name=None, path=None, command=None, metadata=None,
):
    cmd_redacted = None
    cmd_fp = None
    if command:
        cmd_redacted, _ = redact_text(command, max_length=300)
        cmd_fp = _command_fingerprint(command)
    con.execute(
        """
        INSERT INTO brain_contract_events (
            contract_id, project_id, session_id, event_type, tool_name, path,
            command_preview_redacted, command_fingerprint, decision, reason,
            metadata_json, redaction_status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'clean', ?)
        """,
        (
            contract_id, project_id, session_id, event_type, tool_name,
            path, cmd_redacted, cmd_fp, decision, reason,
            dumps(metadata or {}), iso_now(),
        ),
    )


def get_contract(con, contract_id):
    row = con.execute("SELECT * FROM brain_contracts WHERE id = ?", (contract_id,)).fetchone()
    return contract_row_to_dict(row) if row else None


def get_active_contract(con, project_id):
    row = con.execute(
        """
        SELECT * FROM brain_contracts
        WHERE project_id = ? AND status = 'active'
        ORDER BY created_at DESC LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    return contract_row_to_dict(row) if row else None


def list_contracts(con, project_id, status=None, limit=20):
    params = [project_id]
    where = "project_id = ?"
    if status:
        where += " AND status = ?"
        params.append(status)
    rows = con.execute(
        f"SELECT * FROM brain_contracts WHERE {where} ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [contract_row_to_dict(row) for row in rows]


def get_recent_events(con, contract_id, limit=10):
    rows = con.execute(
        "SELECT * FROM brain_contract_events WHERE contract_id = ? ORDER BY created_at DESC LIMIT ?",
        (contract_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def create_contract(
    con,
    project_id,
    task_goal,
    title=None,
    mode="warn",
    allowed_files=None,
    forbidden_files=None,
    allowed_commands=None,
    forbidden_commands=None,
    max_files_changed=None,
    max_lines_changed=None,
    required_tests=None,
    stop_conditions=None,
    review_checklist=None,
    notes=None,
    session_id=None,
    replace=False,
    created_by="cli",
    source="manual",
    confidence=8,
    privacy_class="local-only",
):
    if mode not in CONTRACT_MODES:
        raise ValueError(f"invalid mode: {mode}. Must be one of: {', '.join(sorted(CONTRACT_MODES))}")

    goal_r, s_goal = redact_text(task_goal or "", max_length=1000)
    title_r, s_title = redact_text(title or "", max_length=300)
    notes_r, s_notes = redact_text(notes or "", max_length=1000)
    allowed_r, s_allowed = _redact_list(allowed_files or [])
    forbidden_r, s_forbidden = _redact_list(forbidden_files or [])
    allowed_cmds_r, s_acmds = _redact_list(allowed_commands or [])
    forbidden_cmds_r, s_fcmds = _redact_list(forbidden_commands or [])
    required_r, s_required = _redact_list(required_tests or [])
    stop_r, s_stop = _redact_list(stop_conditions or [])
    review_r, s_review = _redact_list(review_checklist or [])

    redaction_status = combine_status(
        s_goal, s_title, s_notes, s_allowed, s_forbidden,
        s_acmds, s_fcmds, s_required, s_stop, s_review,
    )

    if not goal_r:
        raise ValueError("task_goal is required")

    confidence = _clamp_confidence(confidence)
    now = iso_now()

    existing_active = get_active_contract(con, project_id)
    if existing_active:
        if not replace:
            raise ValueError(
                f"An active contract already exists (id={existing_active['id']}). "
                "Pass --replace to close the existing contract and create a new one."
            )
        con.execute(
            "UPDATE brain_contracts SET status = 'closed', closed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, existing_active["id"]),
        )
        _record_event(
            con, existing_active["id"], project_id, "replaced", "info",
            "replaced by new contract",
            metadata={"replaced_by_goal": goal_r[:100]},
        )

    cur = con.execute(
        """
        INSERT INTO brain_contracts (
            project_id, session_id, title, task_goal, mode,
            allowed_files_json, forbidden_files_json,
            allowed_commands_json, forbidden_commands_json,
            max_files_changed, max_lines_changed,
            required_tests_json, recorded_tests_json,
            stop_conditions_json, review_checklist_json,
            notes, status, violation_count,
            created_by, source, confidence, privacy_class, redaction_status,
            started_at, closed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, 'active', 0,
                  ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            project_id, session_id, title_r or None, goal_r, mode,
            dumps(allowed_r), dumps(forbidden_r),
            dumps(allowed_cmds_r), dumps(forbidden_cmds_r),
            max_files_changed, max_lines_changed,
            dumps(required_r), dumps(stop_r), dumps(review_r),
            notes_r or None, created_by, source,
            confidence, privacy_class, redaction_status,
            now, now, now,
        ),
    )
    contract_id = cur.lastrowid
    _record_event(con, contract_id, project_id, "created", "info", "contract created", session_id=session_id)
    _record_event(con, contract_id, project_id, "activated", "info", "contract activated", session_id=session_id)
    con.commit()
    return get_contract(con, contract_id)


def close_contract(con, contract_id, project_id, reason=None):
    now = iso_now()
    cur = con.execute(
        "UPDATE brain_contracts SET status = 'closed', closed_at = ?, updated_at = ? WHERE id = ? AND project_id = ?",
        (now, now, contract_id, project_id),
    )
    if cur.rowcount < 1:
        return None
    _record_event(con, contract_id, project_id, "closed", "info", reason or "contract closed")
    con.commit()
    return get_contract(con, contract_id)


def complete_contract(con, contract_id, project_id, reason=None):
    contract = get_contract(con, contract_id)
    if not contract or contract["project_id"] != project_id:
        return None, []

    warnings = []
    required = contract.get("required_tests") or []
    recorded_cmds = {r.get("command") for r in (contract.get("recorded_tests") or []) if isinstance(r, dict)}
    missing_tests = [t for t in required if t not in recorded_cmds]
    if missing_tests:
        warnings.append(f"Required tests not recorded: {', '.join(missing_tests[:5])}")

    if contract["mode"] == "strict" and contract["violation_count"] > 0:
        warnings.append(
            f"Contract has {contract['violation_count']} violation(s) recorded. Strict mode active."
        )

    now = iso_now()
    con.execute(
        "UPDATE brain_contracts SET status = 'completed', closed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, contract_id),
    )
    _record_event(
        con, contract_id, project_id, "completed", "info",
        reason or "contract completed",
        metadata={"warnings": warnings},
    )
    con.commit()
    return get_contract(con, contract_id), warnings


def record_test(con, contract_id, project_id, command, result="unknown", summary=None):
    contract = get_contract(con, contract_id)
    if not contract or contract["project_id"] != project_id:
        return None

    cmd_r, _ = redact_text(command or "", max_length=500)
    summary_r, _ = redact_text(summary or "", max_length=500)

    recorded = list(contract.get("recorded_tests") or [])
    entry = {"command": cmd_r, "result": result, "recorded_at": iso_now()}
    if summary_r:
        entry["summary"] = summary_r
    recorded.append(entry)

    now = iso_now()
    con.execute(
        "UPDATE brain_contracts SET recorded_tests_json = ?, updated_at = ? WHERE id = ?",
        (dumps(recorded), now, contract_id),
    )
    _record_event(
        con, contract_id, project_id, "test_recorded", "info",
        f"test recorded: {result}",
        command=command,
        metadata={"result": result, "summary": summary_r or ""},
    )
    con.commit()
    return get_contract(con, contract_id)


def _get_git_changed_files(project_root):
    """Return list of changed relative paths via git, or None if unavailable."""
    try:
        import subprocess
        out_parts = []
        for extra in ([], ["--cached"]):
            r = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"] + extra,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0:
                out_parts.extend(f.strip() for f in r.stdout.splitlines() if f.strip())
        return list(dict.fromkeys(out_parts))
    except Exception:
        return None


def run_contract_check(
    con, contract, project_root=None,
    paths=None, commands=None, check_changed=False,
):
    """Run contract checks, record events, return result dict."""
    mode = contract.get("mode", "warn")
    allowed_files = contract.get("allowed_files") or []
    forbidden_files = contract.get("forbidden_files") or []
    allowed_commands = contract.get("allowed_commands") or []
    forbidden_commands = contract.get("forbidden_commands") or []

    result = {
        "contract_id": contract["id"],
        "mode": mode,
        "status": "pass",
        "violations": [],
        "warnings": [],
        "info": [],
        "path_results": [],
        "command_results": [],
        "changed_files": None,
        "degraded": False,
        "degraded_reason": None,
    }

    if mode == "off":
        result["info"].append("Contract mode is off; check is informational only.")
        return result

    def _handle_path(path_str):
        decision, reason = _check_path(path_str, allowed_files, forbidden_files, project_root)
        rel = normalize_input_path(path_str, project_root) or path_str
        pr = {"path": rel, "decision": decision, "reason": reason}
        result["path_results"].append(pr)
        event_type = "path_denied" if decision == "deny" else "path_allowed"
        _record_event(con, contract["id"], contract["project_id"], event_type, decision, reason, path=rel)
        if decision == "deny":
            msg = f"path: {rel} - {reason}"
            if mode == "strict":
                result["violations"].append(msg)
                con.execute(
                    "UPDATE brain_contracts SET violation_count = violation_count + 1, updated_at = ? WHERE id = ?",
                    (iso_now(), contract["id"]),
                )
            else:
                result["warnings"].append(msg)
        return pr

    for p in paths or []:
        _handle_path(p)

    for cmd in commands or []:
        cmd_r, _ = redact_text(cmd, max_length=300)
        decision, reason = _check_command(cmd, allowed_commands, forbidden_commands)
        if decision == "warn" and mode == "strict":
            decision = "deny"
        cr = {"command": cmd_r, "decision": decision, "reason": reason}
        result["command_results"].append(cr)
        event_type = "command_denied" if decision == "deny" else "command_allowed"
        _record_event(con, contract["id"], contract["project_id"], event_type, decision, reason, command=cmd)
        if decision == "deny":
            msg = f"command: {cmd_r} - {reason}"
            if mode == "strict":
                result["violations"].append(msg)
            else:
                result["warnings"].append(msg)
        elif decision == "warn":
            result["warnings"].append(f"command: {cmd_r} - {reason}")

    if check_changed:
        if project_root:
            changed = _get_git_changed_files(project_root)
            if changed is None:
                result["degraded"] = True
                result["degraded_reason"] = "git not available or not a git repo"
                result["info"].append("Changed-files check skipped: git not available.")
            else:
                filtered = [
                    f for f in changed
                    if not any(part in GENERATED_FOLDERS for part in Path(f).parts)
                ]
                result["changed_files"] = filtered
                for f in filtered:
                    _handle_path(f)
        else:
            result["degraded"] = True
            result["degraded_reason"] = "no project root available"
            result["info"].append("Changed-files check skipped: no project root.")

    required = contract.get("required_tests") or []
    recorded_cmds = {
        r.get("command") for r in (contract.get("recorded_tests") or []) if isinstance(r, dict)
    }
    for test in required:
        if test not in recorded_cmds:
            result["info"].append(f"Required test not yet recorded: {test}")
        else:
            recorded_entry = next(
                (r for r in (contract.get("recorded_tests") or [])
                 if isinstance(r, dict) and r.get("command") == test),
                None,
            )
            if recorded_entry and recorded_entry.get("result") == "fail":
                result["warnings"].append(f"Required test recorded as FAIL: {test}")

    _record_event(
        con, contract["id"], contract["project_id"],
        "checked", "info",
        f"check: {len(result['violations'])} violations, {len(result['warnings'])} warnings",
        metadata={"violations": len(result["violations"]), "warnings": len(result["warnings"])},
    )

    if result["violations"]:
        result["status"] = "violation"
    elif result["warnings"]:
        result["status"] = "warn"

    con.commit()
    return result


def explain_contract(contract, path=None, command=None, project_root=None):
    """Explain path/command decisions for a contract. Non-mutating."""
    mode = contract.get("mode", "warn")
    allowed_files = contract.get("allowed_files") or []
    forbidden_files = contract.get("forbidden_files") or []
    allowed_commands = contract.get("allowed_commands") or []
    forbidden_commands = contract.get("forbidden_commands") or []
    required_tests = contract.get("required_tests") or []
    recorded_tests = contract.get("recorded_tests") or []

    goal_short = contract["task_goal"][:80] + ("..." if len(contract["task_goal"]) > 80 else "")
    lines = [f"Contract #{contract['id']}: {goal_short}", f"Mode: {mode}"]

    if path:
        rel = normalize_input_path(path, project_root) or path
        decision, reason = _check_path(path, allowed_files, forbidden_files, project_root)
        lines += ["", f"Path: {rel}", f"  Decision: {decision}", f"  Reason: {reason}"]
        if allowed_files:
            lines.append(f"  Allowed patterns: {', '.join(allowed_files)}")
        if forbidden_files:
            lines.append(f"  Forbidden patterns: {', '.join(forbidden_files)}")

    if command:
        cmd_r, _ = redact_text(command, max_length=300)
        decision, reason = _check_command(command, allowed_commands, forbidden_commands)
        lines += ["", f"Command: {cmd_r}", f"  Decision: {decision}", f"  Reason: {reason}"]
        if allowed_commands:
            lines.append(f"  Allowed patterns: {', '.join(allowed_commands)}")
        if forbidden_commands:
            lines.append(f"  Forbidden patterns: {', '.join(forbidden_commands)}")

    if required_tests:
        recorded_cmds = {r.get("command") for r in recorded_tests if isinstance(r, dict)}
        lines.append("")
        lines.append("Required tests:")
        for test in required_tests:
            status_label = "recorded" if test in recorded_cmds else "NOT YET RECORDED"
            lines.append(f"  [{status_label}] {test}")

    return "\n".join(lines)


def contract_context_text(contract):
    """Return compact context text for an active contract."""
    lines = ["Active task contract:"]
    lines.append(f"- Goal: {contract['task_goal']}")
    lines.append(f"- Mode: {contract['mode']}")

    allowed = contract.get("allowed_files") or []
    if allowed:
        lines.append(f"- Allowed files: {', '.join(allowed[:6])}")

    forbidden = contract.get("forbidden_files") or []
    if forbidden:
        lines.append(f"- Forbidden files: {', '.join(forbidden[:6])}")

    required = contract.get("required_tests") or []
    if required:
        lines.append(f"- Required tests: {', '.join(required[:4])}")

    stops = contract.get("stop_conditions") or []
    for s in stops[:3]:
        lines.append(f"- Stop if: {s}")

    if contract.get("violation_count", 0) > 0:
        lines.append(f"- Violations so far: {contract['violation_count']}")

    return "\n".join(lines)


def render_contract_status(contract, events=None):
    """Human-readable contract status."""
    if not contract:
        return "No active contract."

    lines = []
    if contract.get("title"):
        lines.append(f"Contract #{contract['id']}: {contract['title']}")
    else:
        lines.append(f"Contract #{contract['id']}")
    lines += [
        f"Goal: {contract['task_goal']}",
        f"Mode: {contract['mode']}",
        f"Status: {contract['status']}",
    ]

    allowed = contract.get("allowed_files") or []
    if allowed:
        lines.append(f"Allowed files: {', '.join(allowed)}")
    forbidden = contract.get("forbidden_files") or []
    if forbidden:
        lines.append(f"Forbidden files: {', '.join(forbidden)}")
    allowed_cmds = contract.get("allowed_commands") or []
    if allowed_cmds:
        lines.append(f"Allowed commands: {', '.join(allowed_cmds)}")
    forbidden_cmds = contract.get("forbidden_commands") or []
    if forbidden_cmds:
        lines.append(f"Forbidden commands: {', '.join(forbidden_cmds)}")

    required = contract.get("required_tests") or []
    recorded = contract.get("recorded_tests") or []
    if required:
        lines.append(f"Required tests ({len(required)}):")
        recorded_cmds = {r.get("command") for r in recorded if isinstance(r, dict)}
        for t in required:
            tag = "recorded" if t in recorded_cmds else "pending"
            lines.append(f"  [{tag}] {t}")
    if recorded:
        lines.append(f"Recorded tests: {len(recorded)}")
        for r in recorded:
            if isinstance(r, dict):
                lines.append(f"  {r.get('command', '?')[:60]} [{r.get('result', '?')}]")

    stops = contract.get("stop_conditions") or []
    for s in stops:
        lines.append(f"Stop if: {s}")
    checklist = contract.get("review_checklist") or []
    for c in checklist:
        lines.append(f"Review: {c}")

    if contract.get("max_files_changed"):
        lines.append(f"Max files changed: {contract['max_files_changed']}")
    if contract.get("max_lines_changed"):
        lines.append(f"Max lines changed: {contract['max_lines_changed']}")

    lines.append(f"Violations: {contract.get('violation_count', 0)}")
    lines.append(f"Created: {contract['created_at']}")

    if events:
        lines.append(f"Recent events ({len(events)}):")
        for ev in events[:5]:
            lines.append(f"  [{ev['event_type']}] {ev['decision']}: {ev['reason']}")

    return "\n".join(lines)


def render_check_result(result):
    """Human-readable check result."""
    lines = [f"Contract check (mode: {result['mode']})"]

    if result.get("degraded"):
        lines.append(f"DEGRADED: {result['degraded_reason']}")

    for item in result.get("violations", []):
        lines.append(f"VIOLATION: {item}")
    for item in result.get("warnings", []):
        lines.append(f"WARNING: {item}")
    for item in result.get("info", []):
        lines.append(f"INFO: {item}")

    if not result.get("violations") and not result.get("warnings"):
        lines.append("No violations found.")

    lines.append(f"Status: {result['status']}")
    return "\n".join(lines)

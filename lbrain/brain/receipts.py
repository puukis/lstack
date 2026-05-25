"""Change Receipts for LBrain."""

import os
import re
import shutil
import subprocess
from pathlib import Path

from .db import dumps, iso_now, loads
from .platform import normalize_path, path_identity, platform_facts
from .redaction import combine_status, redact_json, redact_text

RECEIPT_STATUSES = {"open", "finalized", "abandoned"}
RECEIPT_SOURCES = {"manual", "hook", "contract", "mixed"}
RESULTS = {"pass", "fail", "unknown"}

READ_ONLY_GIT_COMMANDS = {
    ("rev-parse", "--show-toplevel"),
    ("branch", "--show-current"),
    ("rev-parse", "HEAD"),
    ("status", "--porcelain"),
    ("diff", "--name-only"),
    ("diff", "--numstat"),
    ("diff", "--stat"),
}


class GitReceiptError(ValueError):
    pass


def receipts_enabled():
    return os.environ.get("LSTACK_BRAIN_RECEIPTS", "1") != "0"


def receipt_auto_create_enabled():
    return os.environ.get("LSTACK_BRAIN_RECEIPT_AUTO_CREATE", "0") == "1"


def _receipt_redaction_status(*statuses):
    status = combine_status(*statuses)
    return "suspect" if status == "redacted" else status


def _redact_list(values, max_length=500):
    items = []
    statuses = []
    for value in values or []:
        redacted, status = redact_text(str(value), max_length=max_length)
        if redacted:
            items.append(redacted)
        statuses.append(status)
    return items, _receipt_redaction_status(*statuses)


def _redact_path_list(items):
    redacted_items = []
    statuses = []
    for item in items or []:
        path, status = redact_text(str(item.get("path") or ""), max_length=500)
        statuses.append(status)
        redacted_items.append({
            "path": path or "",
            "status": item.get("status") or "",
            "source": item.get("source") or "git",
        })
    return redacted_items, _receipt_redaction_status(*statuses)


def _redact_diff_stats(items):
    redacted_items = []
    statuses = []
    for item in items or []:
        path, status = redact_text(str(item.get("path") or ""), max_length=500)
        statuses.append(status)
        redacted_items.append({
            "path": path or "",
            "added": item.get("added"),
            "deleted": item.get("deleted"),
        })
    return redacted_items, _receipt_redaction_status(*statuses)


def _redact_command_entry(command, result="unknown", source="manual", kind="command"):
    if result not in RESULTS:
        raise ValueError("result must be one of: pass, fail, unknown")
    command_redacted, s_command = redact_text(command or "", max_length=500)
    entry = {
        "command": command_redacted or "",
        "result": result,
        "source": source,
        "kind": kind,
        "recorded_at": iso_now(),
    }
    return entry, _receipt_redaction_status(s_command)


def _redact_evidence(evidence):
    redacted, status = redact_json(evidence or {}, max_string_length=500)
    return redacted, _receipt_redaction_status(status)


def _msys_path(path_value):
    value = str(path_value or "").replace("\\", "/")
    match = re.match(r"^([A-Za-z]):/(.*)$", value)
    if match:
        return f"/{match.group(1).lower()}/{match.group(2)}"
    return value


def _display_git_root(git_root):
    facts = platform_facts()
    normalized = normalize_path(git_root)
    if facts.get("os") == "windows" and facts.get("shell_mode") == "git-bash":
        return _msys_path(normalized)
    return normalized


def _require_git_bash_on_windows():
    facts = platform_facts()
    if facts.get("os") == "windows" and facts.get("shell_mode") != "git-bash":
        raise GitReceiptError("Change Receipts on Windows require Git Bash shell_mode=git-bash.")


def _run_git_readonly(args, cwd=None, timeout=5):
    args_tuple = tuple(args)
    if args_tuple not in READ_ONLY_GIT_COMMANDS:
        raise GitReceiptError(f"Receipt git command is not allowed: git {' '.join(args_tuple)}")
    if not shutil.which("git"):
        raise GitReceiptError("Change Receipts require git on PATH.")
    try:
        result = subprocess.run(
            ["git", *args_tuple],
            cwd=str(cwd or os.getcwd()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitReceiptError("Change Receipts require git on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitReceiptError(f"git {' '.join(args_tuple)} timed out") from exc

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        if args_tuple == ("rev-parse", "--show-toplevel"):
            raise GitReceiptError("Change Receipts require a git worktree. Run this inside a git repository.")
        if args_tuple == ("rev-parse", "HEAD"):
            raise GitReceiptError("Change Receipts require a git HEAD commit.")
        detail = f": {stderr}" if stderr else ""
        raise GitReceiptError(f"git {' '.join(args_tuple)} failed{detail}")
    return (result.stdout or "").strip()


def require_git_worktree(cwd=None):
    _require_git_bash_on_windows()
    root_raw = _run_git_readonly(["rev-parse", "--show-toplevel"], cwd=cwd)
    root = _display_git_root(root_raw)
    branch = _run_git_readonly(["branch", "--show-current"], cwd=root_raw)
    base_commit = _run_git_readonly(["rev-parse", "HEAD"], cwd=root_raw)
    return {"git_root": root, "git_root_cwd": root_raw, "branch": branch, "head": base_commit}


def _status_entries(status_text):
    entries = []
    for line in (status_text or "").splitlines():
        if not line:
            continue
        status = line[:2].strip() or line[:2]
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip()
        if path:
            entries.append({"path": path.replace("\\", "/"), "status": status, "source": "status"})
    return entries


def _name_only_entries(diff_text):
    return [
        {"path": line.strip().replace("\\", "/"), "status": "M", "source": "diff"}
        for line in (diff_text or "").splitlines()
        if line.strip()
    ]


def _git_changed_files(git_root_cwd):
    status_text = _run_git_readonly(["status", "--porcelain"], cwd=git_root_cwd)
    diff_text = _run_git_readonly(["diff", "--name-only"], cwd=git_root_cwd)
    combined = []
    seen = set()
    for item in _name_only_entries(diff_text) + _status_entries(status_text):
        key = item["path"]
        if key not in seen:
            seen.add(key)
            combined.append(item)
    return combined


def _git_diff_stats(git_root_cwd):
    numstat = _run_git_readonly(["diff", "--numstat"], cwd=git_root_cwd)
    items = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added = None if parts[0] == "-" else int(parts[0])
        deleted = None if parts[1] == "-" else int(parts[1])
        items.append({"added": added, "deleted": deleted, "path": parts[2].replace("\\", "/")})
    return items


def _working_tree_dirty(git_root_cwd):
    return bool(_run_git_readonly(["status", "--porcelain"], cwd=git_root_cwd).strip())


def _undo_hint(receipt):
    files = receipt.get("files_changed") or []
    first_path = None
    if files:
        first = files[0]
        first_path = first.get("path") if isinstance(first, dict) else str(first)
    lines = [
        "Safe inspection commands:",
        "  git diff",
        "  git diff --stat",
        f"  git -C {receipt['git_root']} diff",
        f"  git -C {receipt['git_root']} diff --stat",
    ]
    if first_path:
        lines += [
            "",
            "Possible undo commands to review before running:",
            f"  git -C {receipt['git_root']} restore -- {first_path}",
            f"  git -C {receipt['git_root']} checkout -- {first_path}",
        ]
    lines += [
        "  git restore .",
        "",
        "LBrain never executes undo commands automatically.",
    ]
    return "\n".join(lines)


def receipt_row_to_dict(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "contract_id": row["contract_id"],
        "title": row["title"],
        "goal": row["goal"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finalized_at": row["finalized_at"],
        "git_root": row["git_root"],
        "branch": row["branch"],
        "base_commit": row["base_commit"],
        "head_commit": row["head_commit"],
        "base_equals_head": None if row["base_equals_head"] is None else bool(row["base_equals_head"]),
        "working_tree_dirty_start": bool(row["working_tree_dirty_start"]),
        "working_tree_dirty_end": None if row["working_tree_dirty_end"] is None else bool(row["working_tree_dirty_end"]),
        "files_changed": loads(row["files_changed_json"], []),
        "diff_stat": loads(row["diff_stat_json"], []),
        "commands": loads(row["commands_json"], []),
        "tests": loads(row["tests_json"], []),
        "contract_check": loads(row["contract_check_json"], {}),
        "decision_check": loads(row["decision_check_json"], {}),
        "capture_event_ids": loads(row["capture_event_ids_json"], []),
        "auto_learned_ids": loads(row["auto_learned_ids_json"], []),
        "summary": row["summary"],
        "review_notes": row["review_notes"],
        "undo_hint": row["undo_hint"],
        "redaction_status": row["redaction_status"],
        "privacy_class": row["privacy_class"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def event_row_to_dict(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "receipt_id": row["receipt_id"],
        "project_id": row["project_id"],
        "event_type": row["event_type"],
        "summary": row["summary"],
        "command": row["command"],
        "path": row["path"],
        "evidence": loads(row["evidence_json"], {}),
        "capture_event_id": row["capture_event_id"],
        "created_at": row["created_at"],
        "redaction_status": row["redaction_status"],
    }


def get_receipt(con, project_id, receipt_id):
    row = con.execute(
        "SELECT * FROM brain_change_receipts WHERE project_id = ? AND id = ?",
        (project_id, int(receipt_id)),
    ).fetchone()
    return receipt_row_to_dict(row) if row else None


def get_open_receipts(con, project_id):
    rows = con.execute(
        """
        SELECT * FROM brain_change_receipts
        WHERE project_id = ? AND status = 'open'
        ORDER BY started_at DESC, id DESC
        """,
        (project_id,),
    ).fetchall()
    return [receipt_row_to_dict(row) for row in rows]


def get_open_receipt(con, project_id):
    items = get_open_receipts(con, project_id)
    return items[0] if items else None


def list_receipts(con, project_id, status=None, limit=20):
    params = [project_id]
    where = "project_id = ?"
    if status:
        if status not in RECEIPT_STATUSES:
            raise ValueError("invalid receipt status")
        where += " AND status = ?"
        params.append(status)
    rows = con.execute(
        f"""
        SELECT * FROM brain_change_receipts
        WHERE {where}
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (*params, int(limit)),
    ).fetchall()
    return [receipt_row_to_dict(row) for row in rows]


def list_receipt_events(con, project_id, receipt_id, limit=20):
    rows = con.execute(
        """
        SELECT * FROM brain_change_receipt_events
        WHERE project_id = ? AND receipt_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (project_id, int(receipt_id), int(limit)),
    ).fetchall()
    return [event_row_to_dict(row) for row in rows]


def _add_receipt_event(
    con,
    receipt_id,
    project_id,
    event_type,
    summary,
    command=None,
    path=None,
    evidence=None,
    capture_event_id=None,
):
    summary_r, s_summary = redact_text(summary or "", max_length=800)
    command_r, s_command = redact_text(command, max_length=500)
    path_r, s_path = redact_text(path, max_length=500)
    evidence_r, s_evidence = _redact_evidence(evidence or {})
    status = _receipt_redaction_status(s_summary, s_command, s_path, s_evidence)
    now = iso_now()
    cur = con.execute(
        """
        INSERT INTO brain_change_receipt_events (
            receipt_id, project_id, event_type, summary, command, path,
            evidence_json, capture_event_id, created_at, redaction_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(receipt_id),
            project_id,
            event_type,
            summary_r or "",
            command_r,
            path_r,
            dumps(evidence_r),
            capture_event_id,
            now,
            status,
        ),
    )
    return cur.lastrowid, status


def _validate_contract(con, project_id, contract_id):
    if not contract_id:
        return None
    from .contracts import get_contract
    contract = get_contract(con, int(contract_id))
    if not contract or contract["project_id"] != project_id:
        raise ValueError(f"Contract not found: {contract_id}")
    return contract


def _active_contract(con, project_id):
    try:
        from .contracts import get_active_contract
        return get_active_contract(con, project_id)
    except Exception:
        return None


def start_receipt(
    con,
    project,
    title=None,
    goal=None,
    contract_id=None,
    replace=False,
    allow_multiple=False,
    source="manual",
    cwd=None,
):
    if source not in RECEIPT_SOURCES:
        raise ValueError("invalid receipt source")
    git = require_git_worktree(cwd=cwd or project.get("root"))
    git_root_cwd = git["git_root_cwd"]

    existing = get_open_receipts(con, project["id"])
    now = iso_now()
    if existing and not (replace or allow_multiple):
        raise ValueError(
            f"An open receipt already exists (id={existing[0]['id']}). "
            "Pass --replace or --allow-multiple."
        )
    if existing and replace:
        for item in existing:
            con.execute(
                """
                UPDATE brain_change_receipts
                SET status = 'abandoned', finalized_at = ?, summary = ?, updated_at = ?
                WHERE project_id = ? AND id = ? AND status = 'open'
                """,
                (now, "Replaced by a new receipt.", now, project["id"], item["id"]),
            )
            _add_receipt_event(
                con,
                item["id"],
                project["id"],
                "abandoned",
                "Receipt abandoned because a replacement receipt was started.",
            )

    contract = _validate_contract(con, project["id"], contract_id) if contract_id else _active_contract(con, project["id"])
    files, s_files = _redact_path_list(_git_changed_files(git_root_cwd))
    title_r, s_title = redact_text(title or "", max_length=300)
    goal_r, s_goal = redact_text(goal or (contract["task_goal"] if contract else ""), max_length=1000)
    root_r, s_root = redact_text(git["git_root"], max_length=500)
    branch_r, s_branch = redact_text(git["branch"], max_length=200)
    status = _receipt_redaction_status(s_title, s_goal, s_root, s_branch, s_files)
    dirty_start = _working_tree_dirty(git_root_cwd)

    cur = con.execute(
        """
        INSERT INTO brain_change_receipts (
            project_id, contract_id, title, goal, status, started_at, finalized_at,
            git_root, branch, base_commit, head_commit, base_equals_head,
            working_tree_dirty_start, working_tree_dirty_end,
            files_changed_json, diff_stat_json, commands_json, tests_json,
            contract_check_json, decision_check_json, capture_event_ids_json,
            auto_learned_ids_json, summary, review_notes, undo_hint,
            redaction_status, privacy_class, source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'open', ?, NULL, ?, ?, ?, NULL, NULL, ?, NULL,
                  ?, '[]', '[]', '[]', '{}', '{}', '[]', '[]', NULL, NULL, NULL,
                  ?, 'local-only', ?, ?, ?)
        """,
        (
            project["id"],
            contract["id"] if contract else None,
            title_r or None,
            goal_r or None,
            now,
            root_r,
            branch_r,
            git["head"],
            1 if dirty_start else 0,
            dumps(files),
            status,
            source,
            now,
            now,
        ),
    )
    receipt_id = cur.lastrowid
    _add_receipt_event(
        con,
        receipt_id,
        project["id"],
        "started",
        "Change receipt started.",
        evidence={
            "branch": branch_r,
            "base_commit": git["head"],
            "working_tree_dirty_start": dirty_start,
            "changed_files": len(files),
        },
    )
    receipt = get_receipt(con, project["id"], receipt_id)
    hint = _undo_hint(receipt)
    con.execute(
        "UPDATE brain_change_receipts SET undo_hint = ?, updated_at = ? WHERE id = ?",
        (hint, iso_now(), receipt_id),
    )
    con.commit()
    return get_receipt(con, project["id"], receipt_id)


def _resolve_receipt(con, project_id, receipt_id=None, require_open=False):
    receipt = get_receipt(con, project_id, receipt_id) if receipt_id else get_open_receipt(con, project_id)
    if not receipt:
        raise ValueError("No open receipt found." if not receipt_id else f"Receipt not found: {receipt_id}")
    if require_open and receipt["status"] != "open":
        raise ValueError(f"Receipt #{receipt['id']} is not open.")
    return receipt


def _append_unique(existing, values):
    items = list(existing or [])
    seen = set(items)
    for value in values or []:
        if value is not None and value not in seen:
            items.append(value)
            seen.add(value)
    return items


def _append_commands(existing, entries):
    items = list(existing or [])
    for entry in entries or []:
        if entry and entry not in items:
            items.append(entry)
    return items


def _candidate_ids_for_event(con, project_id, capture_event_id):
    rows = con.execute(
        """
        SELECT id, evidence_json FROM brain_memory_candidates
        WHERE project_id = ?
        ORDER BY id
        """,
        (project_id,),
    ).fetchall()
    ids = []
    target = int(capture_event_id)
    for row in rows:
        evidence = loads(row["evidence_json"], {})
        events = evidence.get("events") if isinstance(evidence, dict) else []
        if target in [int(value) for value in events or [] if str(value).isdigit()]:
            ids.append(row["id"])
    return ids


def attach_capture_event(con, project_id, capture_event_id, receipt_id=None):
    receipt = _resolve_receipt(con, project_id, receipt_id, require_open=False)
    event = con.execute(
        "SELECT * FROM brain_capture_events WHERE project_id = ? AND id = ?",
        (project_id, int(capture_event_id)),
    ).fetchone()
    if not event:
        raise ValueError(f"Capture event not found: {capture_event_id}")

    capture_ids = _append_unique(receipt["capture_event_ids"], [int(capture_event_id)])
    auto_ids = _append_unique(receipt["auto_learned_ids"], _candidate_ids_for_event(con, project_id, capture_event_id))
    commands = list(receipt["commands"] or [])
    tests = list(receipt["tests"] or [])
    event_type = event["event_type"]
    command = event["command_preview_redacted"]
    path = event["path"]
    evidence = loads(event["evidence_json"], {})

    statuses = []
    if event_type in ("failed_command", "doctor_result") and command:
        entry, status = _redact_command_entry(command, result="fail" if event_type == "failed_command" else "unknown", source="hook")
        commands = _append_commands(commands, [entry])
        statuses.append(status)
    elif event_type == "test_result" and command:
        result_value = (evidence or {}).get("test_result") or "unknown"
        if result_value not in RESULTS:
            result_value = "unknown"
        entry, status = _redact_command_entry(command, result=result_value, source="hook", kind="test")
        tests = _append_commands(tests, [entry])
        statuses.append(status)
    elif event_type == "implementation_diff" and path:
        _, status = redact_text(path, max_length=500)
        statuses.append(status)

    _, evt_status = _add_receipt_event(
        con,
        receipt["id"],
        project_id,
        event_type,
        f"Attached capture event #{capture_event_id} ({event_type}).",
        path=path if event_type == "implementation_diff" else None,
        evidence={"capture_event_id": int(capture_event_id), "capture_event_type": event_type},
        capture_event_id=int(capture_event_id),
    )
    statuses.append(evt_status)
    now = iso_now()
    new_status = _receipt_redaction_status(receipt["redaction_status"], *statuses)
    con.execute(
        """
        UPDATE brain_change_receipts
        SET capture_event_ids_json = ?, auto_learned_ids_json = ?,
            commands_json = ?, tests_json = ?, redaction_status = ?, updated_at = ?
        WHERE project_id = ? AND id = ?
        """,
        (
            dumps(capture_ids),
            dumps(auto_ids),
            dumps(commands),
            dumps(tests),
            new_status,
            now,
            project_id,
            receipt["id"],
        ),
    )
    con.commit()
    return get_receipt(con, project_id, receipt["id"])


def attach_hook_event(con, project, capture_event_id, tool_name=None, file_path=None):
    if not receipts_enabled():
        return None
    receipt = get_open_receipt(con, project["id"])
    if not receipt and receipt_auto_create_enabled() and tool_name in ("Write", "Edit", "MultiEdit"):
        event = con.execute(
            "SELECT event_type FROM brain_capture_events WHERE project_id = ? AND id = ?",
            (project["id"], int(capture_event_id)),
        ).fetchone()
        if not event or event["event_type"] != "implementation_diff":
            return None
        contract = _active_contract(con, project["id"])
        if contract:
            try:
                receipt = start_receipt(
                    con,
                    project,
                    title="Auto receipt",
                    goal=contract.get("task_goal"),
                    contract_id=contract["id"],
                    allow_multiple=False,
                    source="hook",
                    cwd=project.get("root"),
                )
            except Exception:
                receipt = None
    if not receipt:
        return None
    try:
        return attach_capture_event(con, project["id"], capture_event_id, receipt_id=receipt["id"])
    except Exception:
        return None


def record_command(con, project_id, command, result="unknown", receipt_id=None, source="manual"):
    receipt = _resolve_receipt(con, project_id, receipt_id, require_open=True)
    entry, status = _redact_command_entry(command, result=result, source=source, kind="command")
    commands = _append_commands(receipt["commands"], [entry])
    _, evt_status = _add_receipt_event(
        con,
        receipt["id"],
        project_id,
        "command_recorded",
        f"Command recorded: {result}.",
        command=command,
        evidence={"result": result, "source": source},
    )
    con.execute(
        """
        UPDATE brain_change_receipts
        SET commands_json = ?, redaction_status = ?, updated_at = ?
        WHERE project_id = ? AND id = ?
        """,
        (
            dumps(commands),
            _receipt_redaction_status(receipt["redaction_status"], status, evt_status),
            iso_now(),
            project_id,
            receipt["id"],
        ),
    )
    con.commit()
    return get_receipt(con, project_id, receipt["id"])


def record_test(con, project_id, command, result="unknown", receipt_id=None, source="manual"):
    receipt = _resolve_receipt(con, project_id, receipt_id, require_open=True)
    entry, status = _redact_command_entry(command, result=result, source=source, kind="test")
    tests = _append_commands(receipt["tests"], [entry])
    _, evt_status = _add_receipt_event(
        con,
        receipt["id"],
        project_id,
        "test_recorded",
        f"Test recorded: {result}.",
        command=command,
        evidence={"result": result, "source": source},
    )
    con.execute(
        """
        UPDATE brain_change_receipts
        SET tests_json = ?, redaction_status = ?, updated_at = ?
        WHERE project_id = ? AND id = ?
        """,
        (
            dumps(tests),
            _receipt_redaction_status(receipt["redaction_status"], status, evt_status),
            iso_now(),
            project_id,
            receipt["id"],
        ),
    )
    con.commit()
    return get_receipt(con, project_id, receipt["id"])


def _run_contract_check_for_receipt(con, project, receipt):
    contract = _validate_contract(con, project["id"], receipt.get("contract_id")) if receipt.get("contract_id") else _active_contract(con, project["id"])
    if not contract:
        return {}, None
    from .contracts import run_contract_check
    result = run_contract_check(
        con,
        contract,
        project_root=project.get("root"),
        paths=[item.get("path") for item in receipt.get("files_changed", []) if isinstance(item, dict)],
        commands=[item.get("command") for item in receipt.get("commands", []) if isinstance(item, dict)],
        check_changed=True,
    )
    return result, contract["id"]


def _run_decision_check(con, project):
    try:
        from .decisions import check_decisions
        return check_decisions(con, project, record_regressions=False)
    except Exception as exc:
        return {"status": "degraded", "error": str(exc)}


def finalize_receipt(con, project, receipt_id=None, summary=None, cwd=None):
    receipt = _resolve_receipt(con, project["id"], receipt_id, require_open=True)
    git = require_git_worktree(cwd=cwd or project.get("root"))
    if path_identity(receipt["git_root"]) != path_identity(_display_git_root(git["git_root_cwd"])):
        raise GitReceiptError("Current git worktree does not match receipt git root.")

    files, s_files = _redact_path_list(_git_changed_files(git["git_root_cwd"]))
    stats, s_stats = _redact_diff_stats(_git_diff_stats(git["git_root_cwd"]))
    dirty_end = _working_tree_dirty(git["git_root_cwd"])
    head = _run_git_readonly(["rev-parse", "HEAD"], cwd=git["git_root_cwd"])
    summary_r, s_summary = redact_text(summary or "", max_length=1200)

    preview_receipt = {**receipt, "files_changed": files}
    contract_check, contract_id = _run_contract_check_for_receipt(con, project, preview_receipt)
    decision_check = _run_decision_check(con, project)
    review_notes = _review_notes({**receipt, "files_changed": files, "tests": receipt.get("tests") or []}, contract_check)
    hint = _undo_hint({**receipt, "files_changed": files})
    now = iso_now()
    redaction_status = _receipt_redaction_status(receipt["redaction_status"], s_files, s_stats, s_summary)

    con.execute(
        """
        UPDATE brain_change_receipts
        SET status = 'finalized', finalized_at = ?, head_commit = ?,
            base_equals_head = ?, working_tree_dirty_end = ?,
            files_changed_json = ?, diff_stat_json = ?,
            contract_id = COALESCE(contract_id, ?),
            contract_check_json = ?, decision_check_json = ?,
            summary = ?, review_notes = ?, undo_hint = ?,
            redaction_status = ?, updated_at = ?
        WHERE project_id = ? AND id = ?
        """,
        (
            now,
            head,
            1 if receipt["base_commit"] == head else 0,
            1 if dirty_end else 0,
            dumps(files),
            dumps(stats),
            contract_id,
            dumps(contract_check or {}),
            dumps(decision_check or {}),
            summary_r or None,
            review_notes,
            hint,
            redaction_status,
            now,
            project["id"],
            receipt["id"],
        ),
    )
    _add_receipt_event(
        con,
        receipt["id"],
        project["id"],
        "finalized",
        "Change receipt finalized.",
        evidence={
            "head_commit": head,
            "base_equals_head": receipt["base_commit"] == head,
            "working_tree_dirty_end": dirty_end,
            "changed_files": len(files),
            "diff_stat_entries": len(stats),
        },
    )
    con.commit()

    try:
        from .capture import record_event
        result = record_event(
            con,
            project["id"],
            event_type="receipt_finalized",
            summary=f"Receipt #{receipt['id']} finalized.",
            source="manual",
            evidence={"receipt_id": receipt["id"], "changed_files": len(files), "tests": len(receipt.get("tests") or [])},
            allow_auto_promote=False,
        )
        attach_capture_event(con, project["id"], result["event"]["id"], receipt_id=receipt["id"])
    except Exception:
        pass

    return get_receipt(con, project["id"], receipt["id"])


def abandon_receipt(con, project_id, receipt_id=None, reason=None):
    receipt = _resolve_receipt(con, project_id, receipt_id, require_open=False)
    if receipt["status"] == "finalized":
        raise ValueError(f"Receipt #{receipt['id']} is already finalized.")
    reason_r, s_reason = redact_text(reason or "Receipt abandoned.", max_length=1000)
    now = iso_now()
    con.execute(
        """
        UPDATE brain_change_receipts
        SET status = 'abandoned', finalized_at = ?, summary = ?,
            redaction_status = ?, updated_at = ?
        WHERE project_id = ? AND id = ?
        """,
        (
            now,
            reason_r,
            _receipt_redaction_status(receipt["redaction_status"], s_reason),
            now,
            project_id,
            receipt["id"],
        ),
    )
    _add_receipt_event(con, receipt["id"], project_id, "abandoned", reason_r or "Receipt abandoned.")
    con.commit()
    return get_receipt(con, project_id, receipt["id"])


def receipt_status(con, project, require_current_git=True):
    receipt = get_open_receipt(con, project["id"])
    if receipt and require_current_git:
        require_git_worktree(cwd=project.get("root"))
    events = list_receipt_events(con, project["id"], receipt["id"], limit=5) if receipt else []
    warnings = []
    if receipt and not receipt.get("tests"):
        warnings.append("No tests recorded for open receipt.")
    return {
        "open_receipt": receipt,
        "open_receipt_count": len(get_open_receipts(con, project["id"])),
        "changed_files_count": len(receipt.get("files_changed") or []) if receipt else 0,
        "linked_contract_id": receipt.get("contract_id") if receipt else None,
        "recent_events": events,
        "tests_recorded": len(receipt.get("tests") or []) if receipt else 0,
        "warnings": warnings,
    }


def explain_receipt(con, project, receipt_id=None):
    receipt = get_receipt(con, project["id"], receipt_id) if receipt_id else get_open_receipt(con, project["id"])
    if not receipt:
        rows = list_receipts(con, project["id"], status="finalized", limit=1)
        receipt = rows[0] if rows else None
    if not receipt:
        return {"receipt": None, "message": "No receipt found.", "missing": ["receipt"]}

    missing = []
    if not receipt.get("tests"):
        missing.append("tests")
    if not receipt.get("summary") and receipt["status"] != "open":
        missing.append("summary")
    contract_status = "no contract linked"
    check = receipt.get("contract_check") or {}
    if receipt.get("contract_id"):
        contract_status = check.get("status") or "not checked yet"
    review = _review_notes(receipt, check)
    return {
        "receipt": receipt,
        "why": receipt.get("goal") or receipt.get("title") or "Change tracking for this task.",
        "captured": {
            "git": bool(receipt.get("base_commit")),
            "files_changed": len(receipt.get("files_changed") or []),
            "commands": len(receipt.get("commands") or []),
            "tests": len(receipt.get("tests") or []),
            "capture_events": len(receipt.get("capture_event_ids") or []),
            "auto_learned": len(receipt.get("auto_learned_ids") or []),
        },
        "missing": missing,
        "contract_status": contract_status,
        "review": review,
    }


def _review_notes(receipt, contract_check=None):
    notes = []
    changed = receipt.get("files_changed") or []
    tests = receipt.get("tests") or []
    if changed:
        notes.append(f"Review {len(changed)} changed file(s) with git diff.")
    else:
        notes.append("No changed files were captured.")
    if not tests:
        notes.append("No tests were recorded on this receipt.")
    check = contract_check or receipt.get("contract_check") or {}
    if check.get("status") in ("warn", "violation"):
        notes.append(f"Contract check status: {check.get('status')}.")
    elif receipt.get("contract_id"):
        notes.append("Contract check recorded no blocking violations.")
    return " ".join(notes)


def render_receipt_status(data):
    receipt = data.get("open_receipt")
    if not receipt:
        return "No open receipt."
    lines = [
        f"Open receipt #{receipt['id']}: {receipt.get('title') or '(untitled)'}",
        f"Goal: {receipt.get('goal') or '(none)'}",
        f"Git: {receipt.get('branch') or '-'} @ {receipt.get('base_commit')[:12]}",
        f"Changed files: {data.get('changed_files_count', 0)}",
        f"Linked contract: {receipt.get('contract_id') or 'none'}",
        f"Recorded tests: {data.get('tests_recorded', 0)}",
    ]
    for warning in data.get("warnings") or []:
        lines.append(f"Warning: {warning}")
    events = data.get("recent_events") or []
    if events:
        lines.append(f"Recent events: {len(events)}")
        for event in events[:5]:
            lines.append(f"  [{event['event_type']}] {event['summary'][:80]}")
    return "\n".join(lines)


def render_receipt_list(items):
    if not items:
        return "No receipts found."
    lines = []
    for item in items:
        title = item.get("title") or "(untitled)"
        lines.append(f"#{item['id']} [{item['status']}] {title} - {item.get('branch') or '-'}")
    return "\n".join(lines)


def render_receipt_show(receipt, events=None):
    if not receipt:
        return "Receipt not found."
    lines = [
        f"Receipt #{receipt['id']}: {receipt.get('title') or '(untitled)'}",
        f"Status: {receipt['status']}",
        f"Goal: {receipt.get('goal') or '(none)'}",
        f"Git root: {receipt['git_root']}",
        f"Branch: {receipt.get('branch') or '-'}",
        f"Base: {receipt['base_commit']}",
        f"Head: {receipt.get('head_commit') or '-'}",
        f"Dirty start/end: {receipt['working_tree_dirty_start']} / {receipt['working_tree_dirty_end']}",
        f"Contract: {receipt.get('contract_id') or 'none'}",
        f"Changed files: {len(receipt.get('files_changed') or [])}",
    ]
    for item in receipt.get("files_changed") or []:
        lines.append(f"  {item.get('path') if isinstance(item, dict) else item}")
    lines += [
        f"Diff stats: {len(receipt.get('diff_stat') or [])}",
        f"Commands: {len(receipt.get('commands') or [])}",
        f"Tests: {len(receipt.get('tests') or [])}",
        f"Capture events: {len(receipt.get('capture_event_ids') or [])}",
        f"Auto-learned IDs: {len(receipt.get('auto_learned_ids') or [])}",
        f"Redaction: {receipt.get('redaction_status')}",
    ]
    if receipt.get("summary"):
        lines.append(f"Summary: {receipt['summary']}")
    if receipt.get("review_notes"):
        lines.append(f"Review: {receipt['review_notes']}")
    if events:
        lines.append(f"Receipt events ({len(events)}):")
        for event in events:
            lines.append(f"  [{event['event_type']}] {event['summary']}")
    return "\n".join(lines)


def render_receipt_explain(explanation):
    receipt = explanation.get("receipt")
    if not receipt:
        return explanation.get("message", "No receipt found.")
    lines = [
        f"Receipt #{receipt['id']} exists to track: {explanation.get('why')}",
        f"Status: {receipt['status']}",
        f"Contract: {explanation.get('contract_status')}",
        "Captured:",
    ]
    captured = explanation.get("captured") or {}
    for key in ("files_changed", "commands", "tests", "capture_events", "auto_learned"):
        lines.append(f"  {key}: {captured.get(key, 0)}")
    missing = explanation.get("missing") or []
    lines.append("Missing: " + (", ".join(missing) if missing else "nothing critical"))
    lines.append("Review: " + (explanation.get("review") or "Review git diff before shipping."))
    return "\n".join(lines)

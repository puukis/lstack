"""Database helpers for LBrain."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .project import project_info
from .schema import init_schema

DB_PATH = Path(os.environ.get("LSTACK_DB_PATH", str(Path.home() / ".claude" / "memory" / "lstack.db")))


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path=None, initialize=True, create=True):
    db_path = Path(path or DB_PATH)
    if create:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    elif not db_path.exists():
        raise sqlite3.Error(f"DB does not exist: {db_path}")
    con = sqlite3.connect(str(db_path))
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        if initialize:
            init_schema(con)
    except Exception:
        con.close()
        raise
    return con


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def loads(value, default=None):
    if value is None:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def ensure_project(con, cwd=None):
    info = project_info(cwd)
    now = iso_now()
    row = con.execute(
        "SELECT id FROM brain_projects WHERE root_path_hash = ?",
        (info["root_path_hash"],),
    ).fetchone()
    if row:
        project_id = row["id"]
        con.execute(
            """
            UPDATE brain_projects
            SET root_path_display = ?, repo_id = ?, git_remote_hash = ?, git_branch = ?,
                name = ?, platform = ?, shell_mode = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                info["root_path_display"],
                info["repo_id"],
                info["git_remote_hash"],
                info["git_branch"],
                info["name"],
                info["platform"],
                info["shell_mode"],
                now,
                project_id,
            ),
        )
    else:
        cur = con.execute(
            """
            INSERT INTO brain_projects (
                root_path_hash, root_path_display, repo_id, git_remote_hash, git_branch,
                name, platform, shell_mode, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                info["root_path_hash"],
                info["root_path_display"],
                info["repo_id"],
                info["git_remote_hash"],
                info["git_branch"],
                info["name"],
                info["platform"],
                info["shell_mode"],
                now,
                now,
            ),
        )
        project_id = cur.lastrowid
    con.commit()
    info["id"] = project_id
    return info


def latest_passport_row(con, project_id):
    return con.execute(
        """
        SELECT * FROM brain_passports
        WHERE project_id = ?
        ORDER BY version DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()


def row_to_passport(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "version": row["version"],
        "stack": loads(row["stack_json"], []),
        "commands": loads(row["commands_json"], {}),
        "paths": loads(row["paths_json"], {}),
        "rules": loads(row["rules_json"], {}),
        "architecture_summary": row["architecture_summary"],
        "danger_zones": loads(row["danger_zones_json"], []),
        "manual_overrides": loads(row["manual_overrides_json"], {}),
        "detected_at": row["detected_at"],
        "source": row["source"],
        "confidence": row["confidence"],
        "privacy_class": row["privacy_class"],
        "redaction_status": row["redaction_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def project_counts(con, project_id):
    attempts = con.execute(
        "SELECT COUNT(*) FROM brain_attempts WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]
    decisions = con.execute(
        "SELECT COUNT(*) FROM brain_context_decisions WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]
    passports = con.execute(
        "SELECT COUNT(*) FROM brain_passports WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]
    brain_decisions = con.execute(
        "SELECT COUNT(*) FROM brain_decisions WHERE project_id = ? AND scope = 'project'",
        (project_id,),
    ).fetchone()[0]
    active_decisions = con.execute(
        "SELECT COUNT(*) FROM brain_decisions WHERE project_id = ? AND scope = 'project' AND status = 'active'",
        (project_id,),
    ).fetchone()[0]
    pending_candidates = con.execute(
        "SELECT COUNT(*) FROM brain_memory_candidates WHERE project_id = ? AND scope = 'project' AND status = 'pending'",
        (project_id,),
    ).fetchone()[0]
    capture_events = con.execute(
        "SELECT COUNT(*) FROM brain_capture_events WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]
    return {
        "attempts": attempts,
        "context_decisions": decisions,
        "passports": passports,
        "brain_decisions": brain_decisions,
        "active_decisions": active_decisions,
        "pending_candidates": pending_candidates,
        "capture_events": capture_events,
    }

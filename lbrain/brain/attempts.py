"""Failed Attempt Memory for LBrain."""

import hashlib
from .db import dumps, iso_now
from .redaction import combine_status, redact_text

RETRY_POLICIES = {"never", "ask", "after-change", "allowed"}


def command_fingerprint(command):
    if not command:
        return None
    normalized = " ".join(str(command).strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_attempt(retry_policy, confidence):
    if retry_policy not in RETRY_POLICIES:
        raise ValueError(f"invalid retry policy: {retry_policy}")
    try:
        confidence = int(confidence)
    except Exception as exc:
        raise ValueError("confidence must be an integer from 1 to 10") from exc
    if confidence < 1 or confidence > 10:
        raise ValueError("confidence must be from 1 to 10")
    return confidence


def add_attempt(
    con,
    project_id,
    attempted_action,
    command=None,
    files_touched=None,
    error_summary=None,
    root_cause=None,
    why_failed=None,
    replacement_approach=None,
    platform=None,
    retry_policy="ask",
    confidence=7,
    source_session_id=None,
):
    confidence = validate_attempt(retry_policy, confidence)
    action_redacted, s1 = redact_text(attempted_action)
    command_redacted, s2 = redact_text(command)
    error_redacted, s3 = redact_text(error_summary)
    root_redacted, s4 = redact_text(root_cause)
    why_redacted, s5 = redact_text(why_failed)
    replacement_redacted, s6 = redact_text(replacement_approach)
    status = combine_status(s1, s2, s3, s4, s5, s6)
    now = iso_now()
    cur = con.execute(
        """
        INSERT INTO brain_attempts (
            project_id, attempted_action, command_redacted, command_fingerprint,
            files_touched_json, error_summary, root_cause, why_failed,
            replacement_approach, platform, retry_policy, status, source_session_id,
            confidence, privacy_class, redaction_status, created_at, updated_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            action_redacted,
            command_redacted,
            command_fingerprint(command),
            dumps(files_touched or []),
            error_redacted,
            root_redacted,
            why_redacted,
            replacement_redacted,
            platform,
            retry_policy,
            "active",
            source_session_id,
            confidence,
            "local-only",
            status,
            now,
            now,
            now,
        ),
    )
    con.commit()
    return get_attempt(con, cur.lastrowid)


def attempt_row_to_dict(row):
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "attempted_action": row["attempted_action"],
        "command_redacted": row["command_redacted"],
        "command_fingerprint": row["command_fingerprint"],
        "files_touched": __import__("json").loads(row["files_touched_json"] or "[]"),
        "error_summary": row["error_summary"],
        "root_cause": row["root_cause"],
        "why_failed": row["why_failed"],
        "replacement_approach": row["replacement_approach"],
        "platform": row["platform"],
        "retry_policy": row["retry_policy"],
        "status": row["status"],
        "confidence": row["confidence"],
        "privacy_class": row["privacy_class"],
        "redaction_status": row["redaction_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_seen_at": row["last_seen_at"],
    }


def get_attempt(con, attempt_id):
    row = con.execute("SELECT * FROM brain_attempts WHERE id = ?", (attempt_id,)).fetchone()
    return attempt_row_to_dict(row) if row else None


def list_attempts(con, project_id, limit=20):
    rows = con.execute(
        """
        SELECT * FROM brain_attempts
        WHERE project_id = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (project_id, int(limit)),
    ).fetchall()
    return [attempt_row_to_dict(row) for row in rows]


def search_attempts(con, project_id, query, limit=20):
    like = f"%{query}%"
    rows = con.execute(
        """
        SELECT *,
          CASE
            WHEN attempted_action LIKE ? THEN 5
            WHEN command_redacted LIKE ? THEN 4
            WHEN error_summary LIKE ? THEN 3
            WHEN root_cause LIKE ? THEN 2
            WHEN why_failed LIKE ? THEN 2
            WHEN replacement_approach LIKE ? THEN 1
            ELSE 0
          END AS relevance
        FROM brain_attempts
        WHERE project_id = ? AND (
            attempted_action LIKE ? OR command_redacted LIKE ? OR error_summary LIKE ?
            OR root_cause LIKE ? OR why_failed LIKE ? OR replacement_approach LIKE ?
        )
        ORDER BY relevance DESC, confidence DESC, updated_at DESC, id DESC
        LIMIT ?
        """,
        (like, like, like, like, like, like, project_id, like, like, like, like, like, like, int(limit)),
    ).fetchall()
    return [attempt_row_to_dict(row) for row in rows]


def render_attempts(items):
    if not items:
        return "No failed attempts found."
    lines = []
    for item in items:
        lines.append(f"[{item['id']}] {item['attempted_action']} ({item['retry_policy']}, confidence {item['confidence']}/10)")
        if item.get("command_redacted"):
            lines.append(f"  command: {item['command_redacted']}")
        if item.get("why_failed"):
            lines.append(f"  why: {item['why_failed']}")
        if item.get("replacement_approach"):
            lines.append(f"  replacement: {item['replacement_approach']}")
    return "\n".join(lines)


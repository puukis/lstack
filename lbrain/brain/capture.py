"""Deterministic auto-capture events and memory candidates."""

import re

from .attempts import add_attempt, command_fingerprint
from .db import dumps, iso_now, loads
from .decisions import DECISION_SCOPES, add_decision
from .redaction import combine_status, redact_json, redact_text

EVENT_TYPES = {
    "failed_command",
    "repeated_failed_command",
    "successful_replacement",
    "platform_detection",
    "package_manager_detection",
    "user_correction",
    "explicit_learning_marker",
    "implementation_diff",
    "doctor_result",
    "test_result",
    "regression_signal",
}

CANDIDATE_TYPES = {
    "failed_attempt",
    "implementation_decision",
    "platform_fact",
    "project_convention",
    "rule_candidate",
    "regression_warning",
}

PROPOSED_TARGETS = {"brain_attempts", "brain_decisions", "structured_learning", "future_rule", "none"}
STATUSES = {"pending", "active", "approved", "rejected", "promoted", "superseded", "stale"}


def _clamp_confidence(value):
    try:
        confidence = int(value)
    except Exception as exc:
        raise ValueError("confidence must be an integer from 1 to 10") from exc
    return max(1, min(10, confidence))


def _candidate_redaction_status(*statuses):
    status = combine_status(*statuses)
    return "suspect" if status == "redacted" else status


def _slug(value, fallback="candidate"):
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text or fallback)[:80]


def _validate_event_type(event_type):
    if event_type not in EVENT_TYPES:
        raise ValueError(f"invalid capture event type: {event_type}")
    return event_type


def _validate_candidate_type(candidate_type):
    if candidate_type not in CANDIDATE_TYPES:
        raise ValueError(f"invalid candidate type: {candidate_type}")
    return candidate_type


def _validate_target(target):
    if target not in PROPOSED_TARGETS:
        raise ValueError(f"invalid proposed target: {target}")
    return target


def _merge_evidence(existing, incoming):
    existing = existing if isinstance(existing, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    merged = dict(existing)
    for key, value in incoming.items():
        if key == "events":
            old = merged.get("events") if isinstance(merged.get("events"), list) else []
            new = value if isinstance(value, list) else [value]
            merged["events"] = sorted({item for item in old + new if item is not None})
        elif key == "signals":
            old = merged.get("signals") if isinstance(merged.get("signals"), list) else []
            new = value if isinstance(value, list) else [value]
            merged["signals"] = old + [item for item in new if item not in old]
        elif key == "decision_fields":
            fields = dict(merged.get("decision_fields") or {})
            fields.update(value or {})
            merged["decision_fields"] = fields
        else:
            merged[key] = value
    return merged


def event_row_to_dict(row):
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "session_id": row["session_id"],
        "event_type": row["event_type"],
        "source": row["source"],
        "summary": row["summary"],
        "command_fingerprint": row["command_fingerprint"],
        "command_preview_redacted": row["command_preview_redacted"],
        "path": row["path"],
        "evidence": loads(row["evidence_json"], {}),
        "confidence_delta": row["confidence_delta"],
        "privacy_class": row["privacy_class"],
        "redaction_status": row["redaction_status"],
        "created_at": row["created_at"],
    }


def candidate_row_to_dict(row):
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "scope": row["scope"],
        "candidate_type": row["candidate_type"],
        "key": row["key"],
        "title": row["title"],
        "body": row["body"],
        "rationale": row["rationale"],
        "proposed_target": row["proposed_target"],
        "evidence": loads(row["evidence_json"], {}),
        "confidence": row["confidence"],
        "status": row["status"],
        "source": row["source"],
        "privacy_class": row["privacy_class"],
        "redaction_status": row["redaction_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "promoted_to_type": row["promoted_to_type"],
        "promoted_to_id": row["promoted_to_id"],
    }


def get_event(con, event_id):
    row = con.execute("SELECT * FROM brain_capture_events WHERE id = ?", (event_id,)).fetchone()
    return event_row_to_dict(row) if row else None


def get_candidate(con, project_id, candidate_id, scope="project"):
    row = con.execute(
        "SELECT * FROM brain_memory_candidates WHERE project_id = ? AND scope = ? AND id = ?",
        (project_id, scope, int(candidate_id)),
    ).fetchone()
    return candidate_row_to_dict(row) if row else None


def list_candidates(con, project_id, status="pending", limit=20, scope="project"):
    params = [project_id, scope]
    where = "project_id = ? AND scope = ?"
    if status:
        where += " AND status = ?"
        params.append(status)
    rows = con.execute(
        f"""
        SELECT * FROM brain_memory_candidates
        WHERE {where}
        ORDER BY confidence DESC, updated_at DESC, id DESC
        LIMIT ?
        """,
        (*params, int(limit)),
    ).fetchall()
    return [candidate_row_to_dict(row) for row in rows]


def capture_status(con, project_id):
    events = con.execute(
        "SELECT COUNT(*) FROM brain_capture_events WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]
    pending = con.execute(
        "SELECT COUNT(*) FROM brain_memory_candidates WHERE project_id = ? AND scope = 'project' AND status = 'pending'",
        (project_id,),
    ).fetchone()[0]
    approved = con.execute(
        "SELECT COUNT(*) FROM brain_memory_candidates WHERE project_id = ? AND scope = 'project' AND status = 'approved'",
        (project_id,),
    ).fetchone()[0]
    promoted = con.execute(
        "SELECT COUNT(*) FROM brain_memory_candidates WHERE project_id = ? AND scope = 'project' AND status = 'promoted'",
        (project_id,),
    ).fetchone()[0]
    rejected_stale = con.execute(
        """
        SELECT COUNT(*) FROM brain_memory_candidates
        WHERE project_id = ? AND scope = 'project' AND status IN ('rejected', 'stale')
        """,
        (project_id,),
    ).fetchone()[0]
    return {
        "events": events,
        "pending_candidates": pending,
        "approved_candidates": approved,
        "promoted_candidates": promoted,
        "rejected_or_stale_candidates": rejected_stale,
    }


def list_events(con, project_id, limit=20, event_type=None):
    params = [project_id]
    where = "project_id = ?"
    if event_type:
        where += " AND event_type = ?"
        params.append(event_type)
    rows = con.execute(
        f"""
        SELECT * FROM brain_capture_events
        WHERE {where}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (*params, int(limit)),
    ).fetchall()
    return [event_row_to_dict(row) for row in rows]


def explain_event(con, project_id, event_id):
    event = get_event(con, int(event_id))
    if not event or event["project_id"] != project_id:
        return None
    # Find candidates whose evidence references this event
    rows = con.execute(
        """
        SELECT * FROM brain_memory_candidates
        WHERE project_id = ?
          AND (evidence_json LIKE ? OR command_fingerprint = ?)
        ORDER BY created_at DESC
        LIMIT 5
        """,
        (
            project_id,
            f'%"events": [{event_id}%',
            event.get("command_fingerprint") or "",
        ),
    ).fetchall()
    candidates = [candidate_row_to_dict(r) for r in rows if r]
    return {"event": event, "related_candidates": candidates}


def render_events(items):
    if not items:
        return "No capture events found."
    lines = []
    for item in items:
        lines.append(
            f"[{item['id']}] {item['event_type']} ({item['source']}, {item['redaction_status']})"
        )
        lines.append(f"  {item['summary']}")
        if item.get("command_preview_redacted"):
            lines.append(f"  cmd: {item['command_preview_redacted']}")
    return "\n".join(lines)


def undo_event(con, project_id, event_id):
    """Undo auto-promoted items linked to an event.

    Returns dict with event and list of undone actions.
    Raises ValueError if event is not found for this project.
    """
    event = get_event(con, int(event_id))
    if not event or event["project_id"] != project_id:
        raise ValueError(f"event not found: {event_id}")

    now = iso_now()
    fp = event.get("command_fingerprint") or ""
    undone = []

    # Find promoted candidates whose evidence references this event or fingerprint
    rows = con.execute(
        """
        SELECT * FROM brain_memory_candidates
        WHERE project_id = ? AND status IN ('promoted', 'pending', 'approved')
          AND (
            evidence_json LIKE ?
            OR evidence_json LIKE ?
          )
        """,
        (project_id, f'%"events": [{event_id}%', f'%"command_fingerprint": "{fp}"%'),
    ).fetchall()
    candidates = [candidate_row_to_dict(r) for r in rows if r]

    for candidate in candidates:
        if candidate["status"] != "promoted":
            con.execute(
                "UPDATE brain_memory_candidates SET status = 'stale', updated_at = ? WHERE id = ? AND project_id = ?",
                (now, candidate["id"], project_id),
            )
            undone.append({"candidate_id": candidate["id"], "action": "marked_stale"})
            continue

        promoted_type = candidate.get("promoted_to_type")
        promoted_id = candidate.get("promoted_to_id")
        action = "marked_stale"

        if promoted_type == "brain_decisions" and promoted_id:
            con.execute(
                "UPDATE brain_decisions SET status = 'disabled', updated_at = ? WHERE id = ? AND project_id = ?",
                (now, promoted_id, project_id),
            )
            action = f"disabled decision {promoted_id}"
        elif promoted_type == "brain_attempts" and promoted_id:
            con.execute(
                "DELETE FROM brain_attempts WHERE id = ? AND project_id = ?",
                (promoted_id, project_id),
            )
            action = f"deleted attempt {promoted_id}"

        con.execute(
            """
            UPDATE brain_memory_candidates
            SET status = 'stale', promoted_to_type = NULL, promoted_to_id = NULL, updated_at = ?
            WHERE id = ? AND project_id = ?
            """,
            (now, candidate["id"], project_id),
        )
        undone.append({
            "candidate_id": candidate["id"],
            "promoted_type": promoted_type,
            "promoted_id": promoted_id,
            "action": action,
        })

    con.commit()
    return {"event": event, "undone": undone}


def upsert_candidate(
    con,
    project_id,
    candidate_type,
    key,
    title,
    body,
    rationale=None,
    proposed_target="none",
    evidence=None,
    confidence=5,
    source="detected",
    privacy_class="local-only",
    redaction_status=None,
    scope="project",
):
    if scope not in DECISION_SCOPES:
        raise ValueError(f"invalid candidate scope: {scope}")
    if scope == "project" and project_id is None:
        raise ValueError("project-scoped candidates require a project_id")
    candidate_type = _validate_candidate_type(candidate_type)
    proposed_target = _validate_target(proposed_target)
    confidence = _clamp_confidence(confidence)
    key_redacted, s_key = redact_text(key, max_length=120)
    title_redacted, s_title = redact_text(title, max_length=300)
    body_redacted, s_body = redact_text(body, max_length=1200)
    rationale_redacted, s_rationale = redact_text(rationale, max_length=1000)
    evidence_redacted, s_evidence = redact_json(evidence or {}, max_string_length=800)
    final_status = redaction_status or _candidate_redaction_status(s_key, s_title, s_body, s_rationale, s_evidence)
    now = iso_now()

    existing = con.execute(
        """
        SELECT * FROM brain_memory_candidates
        WHERE project_id = ? AND scope = ? AND candidate_type = ? AND key = ?
        """,
        (project_id, scope, candidate_type, key_redacted),
    ).fetchone()
    if existing:
        existing_item = candidate_row_to_dict(existing)
        if existing_item["status"] in ("promoted", "rejected"):
            return existing_item
        merged_evidence = _merge_evidence(existing_item["evidence"], evidence_redacted)
        con.execute(
            """
            UPDATE brain_memory_candidates
            SET title = ?, body = ?, rationale = ?, proposed_target = ?,
                evidence_json = ?, confidence = ?, source = ?,
                privacy_class = ?, redaction_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                title_redacted,
                body_redacted,
                rationale_redacted,
                proposed_target,
                dumps(merged_evidence),
                max(confidence, existing_item["confidence"]),
                source,
                privacy_class,
                _candidate_redaction_status(existing_item["redaction_status"], final_status),
                now,
                existing_item["id"],
            ),
        )
        candidate_id = existing_item["id"]
    else:
        cur = con.execute(
            """
            INSERT INTO brain_memory_candidates (
                project_id, scope, candidate_type, key, title, body, rationale,
                proposed_target, evidence_json, confidence, status, source,
                privacy_class, redaction_status, created_at, updated_at,
                promoted_to_type, promoted_to_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                scope,
                candidate_type,
                key_redacted,
                title_redacted,
                body_redacted,
                rationale_redacted,
                proposed_target,
                dumps(evidence_redacted),
                confidence,
                "pending",
                source,
                privacy_class,
                final_status,
                now,
                now,
                None,
                None,
            ),
        )
        candidate_id = cur.lastrowid
    con.commit()
    return get_candidate(con, project_id, candidate_id, scope=scope)


def _decision_fields_for_runtime():
    return {
        "applies_to": ["bin/lstack", "hooks/*.sh", "scripts/*.sh"],
        "forbidden_patterns": ["python3 ", "python "],
        "required_patterns": ["run_python"],
        "enforcement_hint": "Scan bin/lstack, hooks/*.sh, and scripts/*.sh for direct python/python3 usage.",
    }


def _decision_fields_for_git_bash():
    return {
        "applies_to": [],
        "forbidden_patterns": ["/mnt/c/", "/mnt/d/"],
        "required_patterns": ["/c/"],
    }


def _decision_fields_for_no_claude():
    return {
        "applies_to": ["hooks/*.sh", "hooks/*.py", "scripts/*.sh", "scripts/*.py"],
        "forbidden_patterns": ["claude -p"],
        "required_patterns": [],
    }


def _package_manager_fields(package_manager, forbidden_manager=None):
    forbidden = []
    if forbidden_manager:
        forbidden = [f"{forbidden_manager} install", f"{forbidden_manager} run", f"{forbidden_manager} test"]
    return {
        "applies_to": ["package.json", f"{package_manager}-lock.yaml", "docs/*.md"],
        "forbidden_patterns": forbidden,
        "required_patterns": [package_manager],
    }


def _classify_user_correction(summary):
    text = str(summary or "")
    lowered = text.lower()
    correction_markers = (
        "do not use",
        "don't use",
        "never use",
        "we fixed this",
        "stop using",
        "use ",
        "this is the correct command",
        "don't repeat",
        "do not repeat",
    )
    if not any(marker in lowered for marker in correction_markers):
        return None

    if (
        "python" in lowered
        and any(marker in lowered for marker in ("do not use", "don't use", "never use", "stop using", "again"))
        and any(marker in lowered for marker in ("lstack", "run_python", "runtime python provider"))
    ):
        return {
            "candidate_type": "implementation_decision",
            "key": "runtime-python-provider",
            "title": "Use lstack runtime for Python execution",
            "body": "All lstack production scripts and hooks must use the runtime Python provider or run_python helper instead of direct python/python3 calls.",
            "rationale": "User correction says direct Python commands should not be repeated.",
            "proposed_target": "brain_decisions",
            "confidence": 10,
            "decision_fields": _decision_fields_for_runtime(),
            "auto_promote": True,
        }
    if ("git bash" in lowered and "wsl" in lowered) or "never use wsl" in lowered:
        return {
            "candidate_type": "platform_fact",
            "key": "git-bash-not-wsl",
            "title": "Use Git Bash paths on Windows, not WSL paths",
            "body": "On Windows, prefer Git Bash and MSYS2-style /c/... or /d/... paths, not WSL /mnt/c/... paths.",
            "rationale": "User correction clarified Windows behavior.",
            "proposed_target": "brain_decisions",
            "confidence": 10,
            "decision_fields": _decision_fields_for_git_bash(),
            "auto_promote": True,
        }
    if "claude -p" in lowered and ("hook" in lowered or "recursive" in lowered or "recursion" in lowered):
        return {
            "candidate_type": "implementation_decision",
            "key": "no-claude-in-hooks",
            "title": "Lifecycle hooks must not call Claude recursively",
            "body": "Lifecycle hooks must not call claude -p by default.",
            "rationale": "User correction says recursive Claude calls from hooks must not be repeated.",
            "proposed_target": "brain_decisions",
            "confidence": 10,
            "decision_fields": _decision_fields_for_no_claude(),
            "auto_promote": True,
        }

    pm_match = re.search(r"use\s+([a-z0-9_-]+)\s*,?\s+not\s+([a-z0-9_-]+)", lowered)
    if pm_match:
        use_pm, avoid_pm = pm_match.groups()
        return {
            "candidate_type": "implementation_decision",
            "key": f"use-{use_pm}-not-{avoid_pm}",
            "title": f"Use {use_pm}, not {avoid_pm}",
            "body": f"Use {use_pm} for package commands in this repo instead of {avoid_pm}.",
            "rationale": "User correction explicitly named the correct command family.",
            "proposed_target": "brain_decisions",
            "confidence": 10,
            "decision_fields": _package_manager_fields(use_pm, avoid_pm),
            "auto_promote": True,
        }

    return {
        "candidate_type": "implementation_decision",
        "key": "user-correction-" + _slug(summary),
        "title": "User correction may be a durable implementation decision",
        "body": text,
        "rationale": "Correction marker was present but the target rule was not specific enough to auto-promote.",
        "proposed_target": "brain_decisions",
        "confidence": 7,
        "decision_fields": {},
        "auto_promote": False,
    }


def _classify_platform_detection(summary, evidence):
    lowered = str(summary or "").lower()
    facts = evidence or {}
    os_name = str(facts.get("os") or facts.get("platform") or "").lower()
    shell_mode = str(facts.get("shell_mode") or "").lower()
    if ("windows git bash" in lowered) or (os_name == "windows" and shell_mode == "git-bash"):
        return {
            "candidate_type": "platform_fact",
            "key": "git-bash-not-wsl",
            "title": "Use Git Bash paths on Windows, not WSL paths",
            "body": "On Windows, prefer Git Bash and MSYS2-style /c/... or /d/... paths, not WSL /mnt/c/... paths.",
            "rationale": "Deterministic platform detection found Windows Git Bash.",
            "proposed_target": "brain_decisions",
            "confidence": 8,
            "decision_fields": _decision_fields_for_git_bash(),
            "auto_promote": False,
        }
    if "/mnt/c" in lowered and "git bash" in lowered:
        return {
            "candidate_type": "platform_fact",
            "key": "git-bash-not-wsl",
            "title": "Use Git Bash paths on Windows, not WSL paths",
            "body": "On Windows, prefer Git Bash and MSYS2-style /c/... or /d/... paths, not WSL /mnt/c/... paths.",
            "rationale": "A WSL path was rejected in Git Bash mode.",
            "proposed_target": "brain_decisions",
            "confidence": 8,
            "decision_fields": _decision_fields_for_git_bash(),
            "auto_promote": False,
        }
    return None


def _classify_package_manager(summary, evidence):
    facts = evidence or {}
    package_manager = facts.get("package_manager") or facts.get("packageManager")
    source = str(facts.get("source") or facts.get("package_manager_source") or "").lower()
    if not package_manager and "packageManager" in str(summary):
        parts = str(summary).split()
        package_manager = next((part for part in parts if part in ("pnpm", "npm", "yarn", "bun")), None)
    if not package_manager:
        return None
    pm = str(package_manager).split("@", 1)[0]
    confidence = 8 if "packagemanager" in source.replace(" ", "") else 6
    if facts.get("lockfile_agrees") or facts.get("lockfile") == pm:
        confidence = min(10, confidence + 1)
    return {
        "candidate_type": "project_convention",
        "key": f"package-manager-{pm}",
        "title": f"Use {pm} package commands",
        "body": f"Use {pm} for package commands in this repo.",
        "rationale": "Package manager was detected from package.json packageManager or matching lockfile evidence.",
        "proposed_target": "brain_decisions",
        "confidence": confidence,
        "decision_fields": _package_manager_fields(pm),
        "auto_promote": confidence >= 8,
    }


def _classify_implementation_diff(summary):
    lowered = str(summary or "").lower()
    if "python3" in lowered and ("run_python" in lowered or "runtime" in lowered) and "replaced" in lowered:
        return {
            "candidate_type": "implementation_decision",
            "key": "runtime-python-provider",
            "title": "Use lstack runtime for Python execution",
            "body": "All lstack production scripts and hooks must use the runtime Python provider or run_python helper instead of direct python/python3 calls.",
            "rationale": "Diff evidence replaced direct Python calls with the runtime helper.",
            "proposed_target": "brain_decisions",
            "confidence": 6,
            "decision_fields": _decision_fields_for_runtime(),
            "auto_promote": False,
        }
    if "/mnt/c" in lowered and "/c/" in lowered and "replaced" in lowered:
        return {
            "candidate_type": "platform_fact",
            "key": "git-bash-not-wsl",
            "title": "Use Git Bash paths on Windows, not WSL paths",
            "body": "On Windows, lstack must target Git Bash and MSYS2-style /c/... or /d/... paths, not WSL /mnt/c/... paths.",
            "rationale": "Diff evidence replaced WSL path style with Git Bash path style.",
            "proposed_target": "brain_decisions",
            "confidence": 6,
            "decision_fields": _decision_fields_for_git_bash(),
            "auto_promote": False,
        }
    return None


def _candidate_from_event(con, project_id, event, allow_auto_promote=True):
    evidence = {
        "events": [event["id"]],
        "signals": [event["event_type"]],
        "event_summary": event["summary"],
    }
    if event.get("command_fingerprint"):
        evidence["command_fingerprint"] = event["command_fingerprint"]
        evidence["command_preview"] = event.get("command_preview_redacted")

    event_type = event["event_type"]
    if event_type == "failed_command":
        if not event.get("command_fingerprint"):
            return None
        count = con.execute(
            """
            SELECT COUNT(*) FROM brain_capture_events
            WHERE project_id = ? AND event_type = 'failed_command' AND command_fingerprint = ?
            """,
            (project_id, event["command_fingerprint"]),
        ).fetchone()[0]
        if count < 2:
            return None
        confidence = min(10, 4 + min(count, 4) + max(0, int(event["confidence_delta"])))
        candidate = upsert_candidate(
            con,
            project_id,
            candidate_type="failed_attempt",
            key=f"repeated-failed-command-{event['command_fingerprint'][:12]}",
            title="Repeated failed command",
            body=f"Command failed repeatedly: {event.get('command_preview_redacted') or event['summary']}",
            rationale="Same command fingerprint failed more than once.",
            proposed_target="brain_attempts",
            evidence=evidence,
            confidence=confidence,
            source=event["source"],
            redaction_status=_candidate_redaction_status(event["redaction_status"]),
        )
        # Auto-promote failed attempts at confidence >= 7 (3 failures = reliable signal)
        if allow_auto_promote and candidate["confidence"] >= 7 and candidate["redaction_status"] == "clean":
            try:
                return promote_candidate(con, project_id, candidate["id"], auto=True)["candidate"]
            except ValueError:
                pass
        return candidate

    if event_type == "successful_replacement":
        related = event["evidence"].get("related_command_fingerprint") or event["evidence"].get("related_fingerprint")
        confidence = 5 if related else 4
        return upsert_candidate(
            con,
            project_id,
            candidate_type="failed_attempt",
            key=f"successful-replacement-{(related or event.get('command_fingerprint') or 'unknown')[:12]}",
            title="Successful replacement command",
            body=event["summary"],
            rationale="A command succeeded after a related failed command.",
            proposed_target="brain_attempts",
            evidence=evidence,
            confidence=confidence,
            source=event["source"],
            redaction_status=_candidate_redaction_status(event["redaction_status"]),
        )

    classifier = None
    if event_type in ("user_correction", "explicit_learning_marker"):
        classifier = _classify_user_correction(event["summary"])
    elif event_type == "platform_detection":
        classifier = _classify_platform_detection(event["summary"], event["evidence"])
    elif event_type == "package_manager_detection":
        classifier = _classify_package_manager(event["summary"], event["evidence"])
    elif event_type == "implementation_diff":
        classifier = _classify_implementation_diff(event["summary"])

    if not classifier:
        return None

    evidence["decision_fields"] = classifier.get("decision_fields") or {}
    candidate = upsert_candidate(
        con,
        project_id,
        candidate_type=classifier["candidate_type"],
        key=classifier["key"],
        title=classifier["title"],
        body=classifier["body"],
        rationale=classifier.get("rationale"),
        proposed_target=classifier["proposed_target"],
        evidence=evidence,
        confidence=classifier["confidence"],
        source=event["source"],
        redaction_status=_candidate_redaction_status(event["redaction_status"]),
    )
    if allow_auto_promote and classifier.get("auto_promote") and candidate["confidence"] >= 8 and candidate["redaction_status"] == "clean":
        try:
            return promote_candidate(con, project_id, candidate["id"], auto=True)["candidate"]
        except ValueError:
            return candidate
    return candidate


def record_event(
    con,
    project_id,
    event_type,
    summary,
    source="manual",
    command=None,
    session_id=None,
    path=None,
    evidence=None,
    confidence_delta=0,
    privacy_class="local-only",
    allow_auto_promote=True,
):
    event_type = _validate_event_type(event_type)
    summary_redacted, s_summary = redact_text(summary, max_length=800)
    command_redacted, s_command = redact_text(command, max_length=500)
    path_redacted, s_path = redact_text(path, max_length=500)
    evidence_redacted, s_evidence = redact_json(evidence or {}, max_string_length=800)
    redaction_status = combine_status(s_summary, s_command, s_path, s_evidence)
    now = iso_now()
    cur = con.execute(
        """
        INSERT INTO brain_capture_events (
            project_id, session_id, event_type, source, summary,
            command_fingerprint, command_preview_redacted, path, evidence_json,
            confidence_delta, privacy_class, redaction_status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            session_id,
            event_type,
            source,
            summary_redacted,
            command_fingerprint(command),
            command_redacted,
            path_redacted,
            dumps(evidence_redacted),
            int(confidence_delta),
            privacy_class,
            redaction_status,
            now,
        ),
    )
    con.commit()
    event = get_event(con, cur.lastrowid)
    candidate = _candidate_from_event(con, project_id, event, allow_auto_promote=allow_auto_promote)
    return {"event": event, "candidate": candidate}


def approve_candidate(con, project_id, candidate_id, scope="project"):
    now = iso_now()
    cur = con.execute(
        """
        UPDATE brain_memory_candidates
        SET status = 'approved', updated_at = ?
        WHERE project_id = ? AND scope = ? AND id = ? AND status = 'pending'
        """,
        (now, project_id, scope, int(candidate_id)),
    )
    con.commit()
    if cur.rowcount < 1:
        return get_candidate(con, project_id, candidate_id, scope=scope)
    return get_candidate(con, project_id, candidate_id, scope=scope)


def reject_candidate(con, project_id, candidate_id, reason=None, scope="project"):
    candidate = get_candidate(con, project_id, candidate_id, scope=scope)
    if not candidate:
        return None
    evidence = dict(candidate["evidence"])
    if reason:
        redacted_reason, status = redact_text(reason, max_length=800)
        evidence["reject_reason"] = redacted_reason
        redaction_status = _candidate_redaction_status(candidate["redaction_status"], status)
    else:
        redaction_status = candidate["redaction_status"]
    now = iso_now()
    con.execute(
        """
        UPDATE brain_memory_candidates
        SET status = 'rejected', evidence_json = ?, redaction_status = ?, updated_at = ?
        WHERE project_id = ? AND scope = ? AND id = ?
        """,
        (dumps(evidence), redaction_status, now, project_id, scope, int(candidate_id)),
    )
    con.commit()
    return get_candidate(con, project_id, candidate_id, scope=scope)


def _decision_kwargs_from_candidate(candidate):
    fields = candidate["evidence"].get("decision_fields") or {}
    return {
        "key": candidate["key"],
        "title": candidate["title"],
        "decision": candidate["body"],
        "rationale": candidate.get("rationale"),
        "enforcement_hint": fields.get("enforcement_hint"),
        "applies_to": fields.get("applies_to") or [],
        "forbidden_patterns": fields.get("forbidden_patterns") or [],
        "required_patterns": fields.get("required_patterns") or [],
        "evidence": {
            "candidate_id": candidate["id"],
            "candidate_type": candidate["candidate_type"],
            "signals": candidate["evidence"].get("signals", []),
            "events": candidate["evidence"].get("events", []),
        },
        "source": candidate["source"],
        "confidence": candidate["confidence"],
        "status": "active",
        "privacy_class": candidate["privacy_class"],
        "scope": candidate["scope"],
    }


def promote_candidate(con, project_id, candidate_id, auto=False, scope="project"):
    candidate = get_candidate(con, project_id, candidate_id, scope=scope)
    if not candidate:
        raise ValueError(f"candidate not found: {candidate_id}")
    if candidate["status"] == "promoted":
        return {"candidate": candidate, "promoted": None}
    if candidate["redaction_status"] in ("suspect", "blocked") or (auto and candidate["redaction_status"] != "clean"):
        raise ValueError("candidate cannot be promoted while redaction status is not clean")

    promoted_type = None
    promoted_id = None
    if candidate["proposed_target"] == "brain_decisions" or candidate["candidate_type"] in ("implementation_decision", "platform_fact", "project_convention"):
        decision = add_decision(con, project_id, **_decision_kwargs_from_candidate(candidate))
        promoted_type = "brain_decisions"
        promoted_id = decision["id"]
    elif candidate["proposed_target"] == "brain_attempts" or candidate["candidate_type"] == "failed_attempt":
        evidence = candidate["evidence"]
        attempt = add_attempt(
            con,
            project_id,
            attempted_action=candidate["title"],
            command=evidence.get("command_preview"),
            error_summary=evidence.get("event_summary"),
            why_failed=candidate.get("rationale"),
            replacement_approach=candidate["body"] if candidate["candidate_type"] == "failed_attempt" else None,
            retry_policy="ask",
            confidence=candidate["confidence"],
        )
        promoted_type = "brain_attempts"
        promoted_id = attempt["id"]
    elif candidate["proposed_target"] in ("future_rule", "structured_learning", "none"):
        return approve_candidate(con, project_id, candidate_id, scope=scope)
    else:
        raise ValueError(f"unsupported candidate target: {candidate['proposed_target']}")

    now = iso_now()
    con.execute(
        """
        UPDATE brain_memory_candidates
        SET status = 'promoted', promoted_to_type = ?, promoted_to_id = ?, updated_at = ?
        WHERE project_id = ? AND scope = ? AND id = ?
        """,
        (promoted_type, promoted_id, now, project_id, scope, int(candidate_id)),
    )
    con.commit()
    return {"candidate": get_candidate(con, project_id, candidate_id, scope=scope), "promoted": {"type": promoted_type, "id": promoted_id}}


def explain_candidate(candidate):
    if not candidate:
        return "Candidate not found."
    lines = [
        f"Candidate {candidate['id']}: {candidate['title']}",
        f"Type: {candidate['candidate_type']}",
        f"Status: {candidate['status']}",
        f"Confidence: {candidate['confidence']}/10",
        f"Privacy: {candidate['privacy_class']}; redaction: {candidate['redaction_status']}",
        f"Target: {candidate['proposed_target']}",
        f"Body: {candidate['body']}",
    ]
    if candidate.get("rationale"):
        lines.append(f"Rationale: {candidate['rationale']}")
    if candidate["status"] == "pending":
        if candidate["confidence"] >= 8 and candidate["redaction_status"] == "clean":
            lines.append("Promotion: eligible if target fields are clear.")
        elif candidate["redaction_status"] != "clean":
            lines.append("Promotion: blocked until sensitive content is reviewed.")
        else:
            lines.append("Promotion: pending review because confidence is below 8.")
    lines.append("Evidence:")
    lines.append(dumps(candidate["evidence"]))
    return "\n".join(lines)


def render_candidates(items):
    if not items:
        return "No pending memory candidates found."
    lines = []
    for item in items:
        lines.append(
            f"[{item['id']}] {item['title']} ({item['candidate_type']}, {item['status']}, confidence {item['confidence']}/10)"
        )
        lines.append(f"  target: {item['proposed_target']}")
        lines.append(f"  {item['body']}")
    return "\n".join(lines)

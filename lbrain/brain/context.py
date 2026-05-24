"""Compact context export for LBrain."""

from .attempts import list_attempts, search_attempts
from .capture import list_candidates
from .db import iso_now
from .decisions import format_decision_context, list_context_decisions, list_decisions
from .passport import get_or_refresh_passport, passport_context
from .platform import platform_facts
from .redaction import redact_text


def _safe_active_contract(con, project_id):
    """Return active contract or None, without raising if table is missing."""
    try:
        from .contracts import get_active_contract
        return get_active_contract(con, project_id)
    except Exception:
        return None


def _token_estimate(text):
    return max(1, len(text or "") // 4)


def _safe_learning_rows(con, project_display, limit=5):
    try:
        row = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learnings'").fetchone()
        if not row:
            return []
        rows = con.execute(
            """
            SELECT id, key, type, insight, confidence, source, trusted, created_at
            FROM learnings
            WHERE confidence >= 7
              AND supersedes_id IS NULL
              AND (project = ? OR (project = 'global' AND trusted = 1 AND source = 'user-stated'))
            ORDER BY trusted DESC, confidence DESC, updated_at DESC
            LIMIT ?
            """,
            (project_display, limit),
        ).fetchall()
        items = []
        for row in rows:
            insight, status = redact_text(row["insight"])
            if status != "blocked":
                items.append(
                    {
                        "id": row["id"],
                        "key": row["key"],
                        "type": row["type"],
                        "insight": insight,
                        "confidence": row["confidence"],
                        "source": row["source"],
                    }
                )
        return items
    except Exception:
        return []


def build_context(con, project, target="codex", query=None, explain=False, debug=False, json_mode=False):
    passport = get_or_refresh_passport(con, project, refresh=False)
    facts = platform_facts()
    decisions = []
    included = []
    skipped = []

    platform_text = f"Platform: {facts['os']}; shell: {facts['shell_mode']}; path rule: {facts['path_style']}"
    included.append({"type": "platform", "text": platform_text})
    decisions.append(("platform", None, "included", "current platform facts are always useful", 1, 1.0, platform_text))

    passport_text = passport_context(passport, target)
    included.append({"type": "passport", "id": passport["id"], "text": passport_text})
    decisions.append(("passport", passport["id"], "included", "latest Repo Passport provides commands and package manager", 2, 1.0, passport_text))

    contract = _safe_active_contract(con, project["id"])
    if contract:
        from .contracts import contract_context_text
        contract_text = contract_context_text(contract)
        included.append({"type": "contract", "id": contract["id"], "text": contract_text})
        decisions.append(("contract", contract["id"], "included", "active task contract scopes this task", 2, 1.0, contract_text))
    else:
        skipped.append({"type": "contract", "id": None, "reason": "no active contract for this project"})
        decisions.append(("contract", None, "skipped", "no active contract for this project", 9, 0.0, ""))

    active_decisions, skipped_scoped_decisions = list_context_decisions(con, project, limit=8)
    for item in active_decisions:
        text = format_decision_context(item)
        scope_note = "explicit user-global decision" if item.get("scope") == "user-global" else "active implementation decision for this project"
        included.append({"type": "decision", "id": item["id"], "key": item["key"], "scope": item.get("scope"), "text": text})
        decisions.append(("decision", item["id"], "included", scope_note, 3, 0.9, text))

    for item in skipped_scoped_decisions:
        reason = item.get("skip_reason") or "decision excluded by scope"
        skipped.append({"type": "decision", "id": item["id"], "key": item["key"], "reason": reason})
        decisions.append(("decision", item["id"], "skipped", reason, 9, 0.0, ""))

    attempts = search_attempts(con, project["id"], query, limit=5) if query else list_attempts(con, project["id"], limit=5)
    for attempt in attempts:
        if attempt["confidence"] >= 7 and attempt["retry_policy"] in ("never", "ask", "after-change"):
            text = f"Avoid repeating: {attempt['attempted_action']}"
            if attempt.get("command_redacted"):
                text += f"; command: {attempt['command_redacted']}"
            if attempt.get("why_failed"):
                text += f"; why failed: {attempt['why_failed']}"
            if attempt.get("replacement_approach"):
                text += f"; replacement: {attempt['replacement_approach']}"
            included.append({"type": "attempt", "id": attempt["id"], "text": text})
            decisions.append(("attempt", attempt["id"], "included", "high-confidence failed attempt for this project", 4, 0.8, text))
        else:
            skipped.append({"type": "attempt", "id": attempt["id"], "reason": "low confidence or non-blocking retry policy"})
            decisions.append(("attempt", attempt["id"], "skipped", "low confidence or non-blocking retry policy", 8, 0.1, ""))

    learnings = _safe_learning_rows(con, project["root_path_display"], limit=5)
    for item in learnings:
        text = f"[{item['type']}/{item['key']}] {item['insight']}"
        included.append({"type": "learning", "id": item["id"], "text": text})
        decisions.append(("learning", item["id"], "included", "high-confidence structured learning available locally", 5, 0.5, text))

    if explain or debug:
        # Show skipped contracts
        try:
            from .contracts import list_contracts
            inactive = list_contracts(con, project["id"], limit=10)
            for c in inactive:
                if c["status"] in ("closed", "completed", "expired"):
                    reason = f"contract status={c['status']} is excluded from normal context"
                    skipped.append({"type": "contract", "id": c["id"], "reason": reason})
                    decisions.append(("contract", c["id"], "skipped", reason, 9, 0.0, ""))
        except Exception:
            pass

        pending = list_candidates(con, project["id"], status="pending", limit=5)
        for item in pending:
            reason = "pending memory candidates are excluded from normal context"
            skipped.append({"type": "candidate", "id": item["id"], "key": item["key"], "reason": reason})
            decisions.append(("candidate", item["id"], "skipped", reason, 9, 0.0, ""))
        disabled = list_decisions(con, project["id"], status="disabled", limit=10)
        for item in disabled:
            reason = "disabled decisions are excluded from normal context"
            skipped.append({"type": "decision", "id": item["id"], "key": item["key"], "reason": reason})
            decisions.append(("decision", item["id"], "skipped", reason, 9, 0.0, ""))
        for scope, reason in (
            ("template", "template decisions are inactive examples and are not injected"),
            ("test-fixture", "test fixture decisions are excluded from real context"),
        ):
            for item in list_decisions(con, project["id"], status=None, limit=10, scope=scope):
                skipped.append({"type": "decision", "id": item["id"], "key": item["key"], "reason": reason})
                decisions.append(("decision", item["id"], "skipped", reason, 9, 0.0, ""))

    for item_type, item_id, decision, reason, priority, relevance, text in decisions:
        con.execute(
            """
            INSERT INTO brain_context_decisions (
                project_id, session_id, target, item_type, item_id, decision,
                reason, priority, relevance_score, token_estimate, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project["id"],
                None,
                target,
                item_type,
                item_id,
                decision,
                reason,
                priority,
                relevance,
                _token_estimate(text),
                iso_now(),
            ),
        )
    con.commit()

    if json_mode:
        return {
            "target": target,
            "project": {"id": project["id"], "name": project["name"]},
            "included": included,
            "skipped": skipped,
            "explain": [
                {
                    "item_type": d[0],
                    "item_id": d[1],
                    "decision": d[2],
                    "reason": d[3],
                    "priority": d[4],
                    "relevance_score": d[5],
                }
                for d in decisions
            ],
        }

    title = {
        "claude": "LBrain context for Claude",
        "codex": "LBrain context for Codex",
        "chatgpt": "LBrain context for ChatGPT",
    }.get(target, "LBrain context")
    lines = [title]
    for item in included:
        if item["type"] in ("platform", "passport", "contract"):
            lines.append(item["text"])
        elif item["type"] == "decision":
            if "Implementation decisions:" not in lines:
                lines.append("Implementation decisions:")
            lines.append(f"- {item['text']}")
        else:
            lines.append(f"- {item['text']}")
    if explain:
        lines.append("")
        lines.append("Context decisions:")
        for d in decisions:
            lines.append(f"- {d[2]} {d[0]} {d[1] or ''}: {d[3]}".rstrip())
    text = "\n".join(lines)
    redacted, _ = redact_text(text, max_length=6000)
    return redacted

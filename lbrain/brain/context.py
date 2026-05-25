"""Compact context export for LBrain."""

from .db import iso_now
from .governor import run_governor, governor_summary
from .redaction import redact_text


def _to_compat_included(item):
    """Convert a governor item to the backward-compatible included format."""
    entry = {"type": item["item_type"], "text": item["text"]}
    if item.get("item_id") is not None:
        entry["id"] = item["item_id"]
    if item.get("key"):
        entry["key"] = item["key"]
    if item.get("scope"):
        entry["scope"] = item["scope"]
    # receipt-specific extra fields
    if item["item_type"] == "receipt":
        if "event_count" in item:
            entry["event_count"] = item["event_count"]
        if "contract_result" in item:
            entry["contract_result"] = item["contract_result"]
    return entry


def _to_compat_skipped(item):
    """Convert a governor item to the backward-compatible skipped format."""
    entry = {"type": item["item_type"], "reason": item["reason"]}
    if item.get("item_id") is not None:
        entry["id"] = item["item_id"]
    elif item["item_type"] in ("contract", "receipt"):
        entry["id"] = None
    if item.get("key"):
        entry["key"] = item["key"]
    return entry


def build_context(
    con,
    project,
    target="codex",
    query=None,
    explain=False,
    debug=False,
    json_mode=False,
):
    result = run_governor(
        con, project,
        target=target, query=query, explain=explain, debug=debug,
    )

    # Write decision log to DB
    for item_type, item_id, decision, reason, priority, relevance, text in result[
        "decision_log"
    ]:
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
                max(1, len(text or "") // 4),
                iso_now(),
            ),
        )
    con.commit()

    if json_mode:
        included_compat = [_to_compat_included(it) for it in result["included"]]
        skipped_compat = [_to_compat_skipped(it) for it in result["skipped"]]
        explain_list = [
            {
                "item_type": d[0],
                "item_id": d[1],
                "decision": d[2],
                "reason": d[3],
                "priority": d[4],
                "relevance_score": d[5],
            }
            for d in result["decision_log"]
        ]
        return {
            "target": target,
            "project": {"id": project["id"], "name": project["name"]},
            "included": included_compat,
            "skipped": skipped_compat,
            "explain": explain_list,
            "governor": governor_summary(result),
        }

    # Text mode — format identical to pre-refactor output
    title = {
        "claude": "LBrain context for Claude",
        "codex": "LBrain context for Codex",
        "chatgpt": "LBrain context for ChatGPT",
    }.get(target, "LBrain context")
    lines = [title]
    for item in result["included"]:
        if item["item_type"] in ("platform", "passport", "contract", "receipt"):
            lines.append(item["text"])
        elif item["item_type"] == "decision":
            if "Implementation decisions:" not in lines:
                lines.append("Implementation decisions:")
            lines.append(f"- {item['text']}")
        else:
            lines.append(f"- {item['text']}")
    if explain or debug:
        lines.append("")
        lines.append("Context decisions:")
        for d in result["decision_log"]:
            lines.append(f"- {d[2]} {d[0]} {d[1] or ''}: {d[3]}".rstrip())
    text = "\n".join(lines)
    redacted, _ = redact_text(text, max_length=6000)
    return redacted

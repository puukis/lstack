"""Context Governor policy layer for LBrain.

Assembles context items with full metadata: source feature, priority,
confidence, mandatory flag, token estimate, and skip reasons.
"""

from .attempts import list_attempts, search_attempts
from .capture import list_candidates
from .db import iso_now
from .decisions import format_decision_context, list_context_decisions, list_decisions
from .passport import get_or_refresh_passport, passport_context
from .platform import platform_facts
from .redaction import redact_text

DEFAULT_BUDGETS = {
    "claude": 6000,
    "codex": 6000,
    "chatgpt": 6000,
    "generic": 6000,
}

_MANDATORY_TARGETS = {"claude"}


def _token_estimate(text):
    return max(1, len(text or "") // 4)


def _make_item(
    item_type,
    text,
    source_feature,
    priority,
    confidence,
    relevance_score,
    mandatory,
    included,
    reason,
    *,
    item_id=None,
    key=None,
    title=None,
    scope=None,
    status="active",
    redaction_status="clean",
    **extra,
):
    safe_text, rd_status = redact_text(text or "", max_length=2000)
    if rd_status == "blocked":
        included = False
        reason = "redaction blocked this item"
    actual_rd = rd_status if rd_status != "clean" else redaction_status
    item = {
        "item_type": item_type,
        "item_id": item_id,
        "key": key,
        "title": title,
        "text": safe_text,
        "source_feature": source_feature,
        "priority": priority,
        "confidence": confidence,
        "relevance_score": relevance_score,
        "token_estimate": _token_estimate(safe_text),
        "scope": scope,
        "status": status,
        "mandatory": mandatory,
        "included": included,
        "reason": reason,
        "redaction_status": actual_rd,
    }
    item.update(extra)
    return item


def _safe_active_contract(con, project_id):
    try:
        from .contracts import get_active_contract
        return get_active_contract(con, project_id)
    except Exception:
        return None


def _safe_open_receipt(con, project_id):
    try:
        from .receipts import get_open_receipt, list_receipt_events
        receipt = get_open_receipt(con, project_id)
        if not receipt:
            return None, []
        return receipt, list_receipt_events(con, project_id, receipt["id"], limit=5)
    except Exception:
        return None, []


def _safe_learning_rows(con, project_display, limit=5):
    try:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='learnings'"
        ).fetchone()
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
        result = []
        for row in rows:
            insight, status = redact_text(row["insight"])
            if status != "blocked":
                result.append({
                    "id": row["id"],
                    "key": row["key"],
                    "type": row["type"],
                    "insight": insight,
                    "confidence": row["confidence"],
                    "source": row["source"],
                })
        return result
    except Exception:
        return []


def run_governor(
    con,
    project,
    target="claude",
    query=None,
    explain=False,
    debug=False,
    budget=None,
):
    """Assemble context items with full governor metadata.

    Returns a dict with:
      target, budget, items, included, skipped,
      estimated_tokens, decision_log
    """
    if budget is None:
        budget = DEFAULT_BUDGETS.get(target, 6000)

    is_mandatory_target = target in _MANDATORY_TARGETS
    all_items = []
    decision_log = []  # (item_type, item_id, decision, reason, priority, relevance, text)

    # --- Priority 1: Platform / shell / path rule (mandatory for claude) ---
    facts = platform_facts()
    platform_text = (
        f"Platform: {facts['os']}; shell: {facts['shell_mode']}; "
        f"path rule: {facts['path_style']}"
    )
    item = _make_item(
        "platform", platform_text, "platform", 1, 1.0, 1.0,
        is_mandatory_target, True,
        "current platform facts are always useful",
    )
    all_items.append(item)
    decision_log.append(
        ("platform", None, "included",
         "current platform facts are always useful", 1, 1.0, platform_text)
    )

    # --- Priority 2: Active Task Contract (mandatory if present) ---
    contract = _safe_active_contract(con, project["id"])
    if contract:
        from .contracts import contract_context_text
        contract_text = contract_context_text(contract)
        item = _make_item(
            "contract", contract_text, "task_contracts", 2, 1.0, 1.0,
            True, True,
            "active task contract scopes this task",
            item_id=contract["id"],
        )
        all_items.append(item)
        decision_log.append(
            ("contract", contract["id"], "included",
             "active task contract scopes this task", 2, 1.0, contract_text)
        )
    else:
        item = _make_item(
            "contract", "", "task_contracts", 9, 0.0, 0.0,
            False, False,
            "no active contract for this project",
            status="none",
        )
        all_items.append(item)
        decision_log.append(
            ("contract", None, "skipped",
             "no active contract for this project", 9, 0.0, "")
        )

    # --- Priority 3: Open Change Receipt (mandatory if present) ---
    receipt, receipt_events = _safe_open_receipt(con, project["id"])
    if receipt:
        changed_count = len(receipt.get("files_changed") or [])
        tests_count = len(receipt.get("tests") or [])
        receipt_lines = ["Open change receipt:"]
        receipt_lines.append(
            f"- Receipt #{receipt['id']}: {receipt.get('title') or '(untitled)'}"
        )
        if receipt.get("goal"):
            receipt_lines.append(f"- Goal: {receipt['goal']}")
        if receipt.get("contract_id"):
            receipt_lines.append(f"- Linked contract: #{receipt['contract_id']}")
        receipt_lines.append(f"- Changed files captured: {changed_count}")
        if tests_count:
            receipt_lines.append(f"- Tests recorded: {tests_count}")
        else:
            receipt_lines.append("- Tests recorded: 0 (record tests before finalizing)")
        if debug:
            receipt_lines.append(
                f"- Base/head: {receipt.get('base_commit', '')[:12]} / "
                f"{(receipt.get('head_commit') or '-')[:12]}"
            )
            receipt_lines.append(
                f"- Attached events: {len(receipt.get('capture_event_ids') or [])}"
            )
            receipt_lines.append(
                f"- Commands/tests: {len(receipt.get('commands') or [])}/{tests_count}"
            )
        receipt_text = "\n".join(receipt_lines)
        item = _make_item(
            "receipt", receipt_text, "change_receipts", 3, 1.0, 1.0,
            True, True,
            "open receipt tracks this task's audit trail",
            item_id=receipt["id"],
            event_count=len(receipt_events),
            contract_result=(receipt.get("contract_check") or {}).get("status"),
        )
        all_items.append(item)
        decision_log.append(
            ("receipt", receipt["id"], "included",
             "open receipt tracks this task's audit trail", 3, 1.0, receipt_text)
        )
    else:
        item = _make_item(
            "receipt", "", "change_receipts", 9, 0.0, 0.0,
            False, False,
            "no open receipt for this project",
            status="none",
        )
        all_items.append(item)
        decision_log.append(
            ("receipt", None, "skipped",
             "no open receipt for this project", 9, 0.0, "")
        )

    # --- Priority 4: Repo Passport (mandatory for claude) ---
    passport = get_or_refresh_passport(con, project, refresh=False)
    passport_text = passport_context(passport, target)
    item = _make_item(
        "passport", passport_text, "repo_passport", 4, 1.0, 1.0,
        is_mandatory_target, True,
        "latest Repo Passport provides commands and package manager",
        item_id=passport["id"],
    )
    all_items.append(item)
    decision_log.append(
        ("passport", passport["id"], "included",
         "latest Repo Passport provides commands and package manager", 4, 1.0, passport_text)
    )

    # --- Priority 5: Active Decisions ---
    active_decisions, skipped_scoped_decisions = list_context_decisions(
        con, project, limit=8
    )
    for d_item in active_decisions:
        text = format_decision_context(d_item)
        scope_note = (
            "explicit user-global decision"
            if d_item.get("scope") == "user-global"
            else "active implementation decision for this project"
        )
        item = _make_item(
            "decision", text, "decisions", 5, float(d_item.get("confidence", 8)), 0.9,
            False, True, scope_note,
            item_id=d_item["id"], key=d_item["key"], scope=d_item.get("scope"),
        )
        all_items.append(item)
        decision_log.append(
            ("decision", d_item["id"], "included", scope_note, 3, 0.9, text)
        )

    for d_item in skipped_scoped_decisions:
        reason = d_item.get("skip_reason") or "decision excluded by scope"
        item = _make_item(
            "decision", "", "decisions", 9, 0.0, 0.0,
            False, False, reason,
            item_id=d_item["id"], key=d_item["key"],
        )
        all_items.append(item)
        decision_log.append(
            ("decision", d_item["id"], "skipped", reason, 9, 0.0, "")
        )

    # --- Priority 6: High-confidence Failed Attempts ---
    attempts = (
        search_attempts(con, project["id"], query, limit=5)
        if query
        else list_attempts(con, project["id"], limit=5)
    )
    for attempt in attempts:
        if (
            attempt["confidence"] >= 7
            and attempt["retry_policy"] in ("never", "ask", "after-change")
        ):
            text = f"Avoid repeating: {attempt['attempted_action']}"
            if attempt.get("command_redacted"):
                text += f"; command: {attempt['command_redacted']}"
            if attempt.get("why_failed"):
                text += f"; why failed: {attempt['why_failed']}"
            if attempt.get("replacement_approach"):
                text += f"; replacement: {attempt['replacement_approach']}"
            item = _make_item(
                "attempt", text, "failed_attempt_memory", 6,
                float(attempt["confidence"]), 0.8,
                False, True,
                "high-confidence failed attempt for this project",
                item_id=attempt["id"],
            )
            all_items.append(item)
            decision_log.append(
                ("attempt", attempt["id"], "included",
                 "high-confidence failed attempt for this project", 4, 0.8, text)
            )
        else:
            item = _make_item(
                "attempt", "", "failed_attempt_memory", 8,
                float(attempt.get("confidence", 0)), 0.1,
                False, False,
                "low confidence or non-blocking retry policy",
                item_id=attempt["id"],
            )
            all_items.append(item)
            decision_log.append(
                ("attempt", attempt["id"], "skipped",
                 "low confidence or non-blocking retry policy", 8, 0.1, "")
            )

    # --- Priority 7: High-confidence Structured Learnings ---
    learnings = _safe_learning_rows(con, project["root_path_display"], limit=5)
    for lr in learnings:
        text = f"[{lr['type']}/{lr['key']}] {lr['insight']}"
        item = _make_item(
            "learning", text, "structured_learning", 7,
            float(lr["confidence"]), 0.5,
            False, True,
            "high-confidence structured learning available locally",
            item_id=lr["id"], key=lr["key"],
        )
        all_items.append(item)
        decision_log.append(
            ("learning", lr["id"], "included",
             "high-confidence structured learning available locally", 5, 0.5, text)
        )

    # --- Priority 8/9: Pending candidates / disabled items (debug/explain only) ---
    if explain or debug:
        try:
            from .contracts import list_contracts
            inactive = list_contracts(con, project["id"], limit=10)
            for c in inactive:
                if c["status"] in ("closed", "completed", "expired"):
                    reason = (
                        f"contract status={c['status']} is excluded from normal context"
                    )
                    item = _make_item(
                        "contract", "", "task_contracts", 9, 0.0, 0.0,
                        False, False, reason,
                        item_id=c["id"], status=c["status"],
                    )
                    all_items.append(item)
                    decision_log.append(
                        ("contract", c["id"], "skipped", reason, 9, 0.0, "")
                    )
        except Exception:
            pass

        pending = list_candidates(con, project["id"], status="pending", limit=5)
        for c in pending:
            reason = "pending memory candidates are excluded from normal context"
            item = _make_item(
                "candidate", "", "capture", 9, 0.0, 0.0,
                False, False, reason,
                item_id=c["id"], key=c["key"], status="pending",
            )
            all_items.append(item)
            decision_log.append(
                ("candidate", c["id"], "skipped", reason, 9, 0.0, "")
            )

        disabled = list_decisions(con, project["id"], status="disabled", limit=10)
        for d_item in disabled:
            reason = "disabled decisions are excluded from normal context"
            item = _make_item(
                "decision", "", "decisions", 9, 0.0, 0.0,
                False, False, reason,
                item_id=d_item["id"], key=d_item["key"], status="disabled",
            )
            all_items.append(item)
            decision_log.append(
                ("decision", d_item["id"], "skipped", reason, 9, 0.0, "")
            )

        for scope, reason in (
            ("template", "template decisions are inactive examples and are not injected"),
            (
                "test-fixture",
                "test fixture decisions are excluded from real context",
            ),
        ):
            for d_item in list_decisions(
                con, project["id"], status=None, limit=10, scope=scope
            ):
                item = _make_item(
                    "decision", "", "decisions", 9, 0.0, 0.0,
                    False, False, reason,
                    item_id=d_item["id"], key=d_item["key"], scope=scope,
                )
                all_items.append(item)
                decision_log.append(
                    ("decision", d_item["id"], "skipped", reason, 9, 0.0, "")
                )

    included = [it for it in all_items if it["included"]]
    skipped = [it for it in all_items if not it["included"]]
    estimated_tokens = sum(it["token_estimate"] for it in included)

    return {
        "target": target,
        "budget": budget,
        "items": all_items,
        "included": included,
        "skipped": skipped,
        "estimated_tokens": estimated_tokens,
        "decision_log": decision_log,
    }


def governor_summary(result):
    """Return a compact dict for the overview --json `context_governor` key."""
    top_included = [
        {
            "item_type": it["item_type"],
            "key": it.get("key"),
            "reason": it["reason"],
        }
        for it in result["included"][:5]
    ]
    top_skipped = [
        {
            "item_type": it["item_type"],
            "key": it.get("key"),
            "reason": it["reason"],
        }
        for it in result["skipped"][:5]
    ]
    return {
        "target": result["target"],
        "budget": result["budget"],
        "included_count": len(result["included"]),
        "skipped_count": len(result["skipped"]),
        "estimated_tokens": result["estimated_tokens"],
        "top_included": top_included,
        "top_skipped": top_skipped,
    }

"""Brain overview builder — returns stable overview JSON."""

import datetime

from .db import DB_PATH, latest_passport_row, loads, row_to_passport
from .doctor import run_doctor
from .firewall import firewall_status, run_firewall_check
from .governor import governor_summary, run_governor
from .platform import platform_facts


def build_overview(con, project, target="claude", query=None):
    """Return a stable overview dict. Never mutates DB beyond existing context logging."""
    facts = platform_facts()
    pid = project["id"]

    # Passport
    passport_row = latest_passport_row(con, pid)
    passport = row_to_passport(passport_row)
    if passport:
        passport_data = {
            "available": True,
            "stack": passport.get("stack") or [],
            "package_manager": (passport.get("commands") or {}).get("package_manager"),
            "important_folders": list((passport.get("paths") or {}).get("important", [])),
            "generated_folders": list((passport.get("paths") or {}).get("generated", [])),
            "protected_files": list((passport.get("paths") or {}).get("protected", [])),
        }
    else:
        passport_data = {"available": False}

    # Context Governor
    gov_result = run_governor(con, project, target=target, query=query)
    gov_data = governor_summary(gov_result)

    # AI Mistake Firewall
    fw_result = run_firewall_check(con=con, project=project)
    fw_data = {
        "available": True,
        "status": fw_result["status"],
        "warning_count": fw_result["warning_count"],
        "top_warnings": [
            {
                "severity": w["severity"],
                "source": w["source"],
                "key": w.get("key"),
                "message": w["message"],
            }
            for w in fw_result["warnings"][:3]
        ],
    }

    # Contracts
    active_contract_data = None
    active_count = 0
    try:
        from .contracts import get_active_contract, list_contracts
        active_contract = get_active_contract(con, pid)
        if active_contract:
            active_contract_data = {
                "id": active_contract["id"],
                "mode": active_contract.get("mode"),
                "status": active_contract.get("status"),
            }
        all_contracts = list_contracts(con, pid, limit=100)
        active_count = sum(1 for c in all_contracts if c.get("status") == "active")
    except Exception:
        pass
    contracts_data = {"active": active_contract_data, "active_count": active_count}

    # Receipts
    open_receipt_data = None
    recent_data = []
    try:
        from .receipts import get_open_receipt, list_receipts
        open_receipt = get_open_receipt(con, pid)
        if open_receipt:
            open_receipt_data = {
                "id": open_receipt["id"],
                "title": open_receipt.get("title"),
                "status": open_receipt.get("status"),
            }
        recent_receipts = list_receipts(con, pid, limit=3)
        recent_data = [
            {"id": r["id"], "title": r.get("title"), "status": r.get("status")}
            for r in recent_receipts
        ]
    except Exception:
        pass
    receipts_data = {"open": open_receipt_data, "recent": recent_data}

    # Decisions
    active_dec_count = 0
    top_decisions = []
    try:
        from .decisions import list_decisions
        active_decs = list_decisions(con, pid, status="active", limit=5)
        row = con.execute(
            "SELECT COUNT(*) FROM brain_decisions WHERE project_id = ? AND status = 'active'",
            (pid,),
        ).fetchone()
        active_dec_count = row[0] if row else 0
        top_decisions = [
            {"id": d["id"], "key": d.get("key"), "title": d.get("title")}
            for d in active_decs[:5]
        ]
    except Exception:
        pass
    decisions_data = {"active_count": active_dec_count, "top": top_decisions}

    # Failed Attempts
    attempts_total = 0
    top_attempts = []
    try:
        from .attempts import list_attempts
        attempts = list_attempts(con, pid, limit=5)
        row = con.execute(
            "SELECT COUNT(*) FROM brain_attempts WHERE project_id = ?", (pid,)
        ).fetchone()
        attempts_total = row[0] if row else 0
        top_attempts = [
            {
                "id": a["id"],
                "attempted_action": (a.get("attempted_action") or "")[:80],
                "confidence": a.get("confidence"),
            }
            for a in attempts[:5]
        ]
    except Exception:
        pass
    failed_attempts_data = {"count": attempts_total, "top": top_attempts}

    # Capture
    events_count = 0
    pending_count = 0
    promoted_count = 0
    recent_ev_data = []
    pending_cand_data = []
    try:
        from .capture import capture_status, list_candidates, list_events
        cap_status = capture_status(con, pid)
        events_count = cap_status.get("events_count", 0)
        pending_count = cap_status.get("pending_candidates_count", 0)
        promoted_count = cap_status.get("promoted_candidates_count", 0)
        recent_events = list_events(con, pid, limit=3)
        recent_ev_data = [
            {
                "id": e["id"],
                "event_type": e.get("event_type"),
                "summary": (e.get("summary") or "")[:60],
            }
            for e in recent_events
        ]
        pending_cands = list_candidates(con, pid, status="pending", limit=3)
        pending_cand_data = [
            {"id": c["id"], "key": c.get("key"), "candidate_type": c.get("candidate_type")}
            for c in pending_cands
        ]
    except Exception:
        pass
    capture_data = {
        "events_count": events_count,
        "pending_candidates_count": pending_count,
        "promoted_candidates_count": promoted_count,
        "recent_events": recent_ev_data,
        "pending_candidates": pending_cand_data,
    }

    # Doctor (compact summary)
    dr_status = "warn"
    dr_warnings = []
    dr_failures = []
    try:
        dr = run_doctor()
        dr_status = dr["status"]
        dr_warnings = [c["id"] for c in dr["checks"] if c["status"] == "warn"]
        dr_failures = [c["id"] for c in dr["checks"] if c["status"] == "fail"]
    except Exception:
        pass
    doctor_data = {"status": dr_status, "warnings": dr_warnings, "failures": dr_failures}

    return {
        "schema_version": 1,
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "db_path": str(DB_PATH),
        "project": {
            "id": project["id"],
            "name": project["name"],
            "root_path_display": project.get("root_path_display", ""),
            "git_branch": project.get("git_branch", ""),
        },
        "platform": {
            "os": facts["os"],
            "shell_mode": facts["shell_mode"],
            "path_rule": facts["path_style"],
        },
        "passport": passport_data,
        "context_governor": gov_data,
        "firewall": fw_data,
        "contracts": contracts_data,
        "receipts": receipts_data,
        "decisions": decisions_data,
        "failed_attempts": failed_attempts_data,
        "capture": capture_data,
        "doctor": doctor_data,
    }

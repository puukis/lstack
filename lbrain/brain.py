#!/usr/bin/env python3
"""LBrain CLI."""

import argparse
import json
import sqlite3
import sys

from brain.attempts import add_attempt, list_attempts, render_attempts, search_attempts
from brain.autolearn import autolearn_config
from brain.capture import (
    approve_candidate,
    capture_status,
    explain_candidate,
    explain_event,
    get_candidate,
    list_candidates,
    list_events,
    promote_candidate,
    record_event,
    reject_candidate,
    render_candidates,
    render_events,
    undo_event,
)
from brain.context import build_context
from brain.db import DB_PATH, connect, ensure_project, latest_passport_row, project_counts, row_to_passport
from brain.decisions import (
    add_decision,
    check_decisions,
    disable_decision,
    get_decision,
    list_decisions,
    render_check_result,
    render_decisions,
    search_decisions,
    seed_lstack_default_decisions,
)
from brain.contracts import (
    close_contract,
    complete_contract,
    contract_row_to_dict,
    create_contract,
    explain_contract,
    get_active_contract,
    get_contract,
    get_recent_events,
    list_contracts,
    record_test,
    render_check_result as render_contract_check_result,
    render_contract_status,
    run_contract_check,
)
from brain.doctor import render_doctor, run_doctor
from brain.passport import get_or_refresh_passport, passport_context, passport_summary
from brain.platform import platform_facts
from brain.attempts import command_fingerprint
from brain.governor import run_governor, governor_summary
from brain.firewall import (
    firewall_status,
    firewall_explain,
    run_firewall_check,
    render_firewall_check,
    render_firewall_status,
)
from brain.overview import build_overview
from brain.receipts import (
    GitReceiptError,
    abandon_receipt,
    attach_capture_event,
    explain_receipt,
    finalize_receipt,
    get_receipt,
    list_receipt_events,
    list_receipts,
    record_command as receipt_record_command,
    record_test as receipt_record_test,
    render_receipt_explain,
    render_receipt_list,
    render_receipt_show,
    render_receipt_status,
    receipt_status,
    start_receipt,
)


def print_json(data):
    print(json.dumps(data, indent=2, sort_keys=True))


def cmd_status(args):
    con = connect()
    project = ensure_project(con)
    seeded = seed_lstack_default_decisions(con, project)
    counts = project_counts(con, project["id"])
    passport = row_to_passport(latest_passport_row(con, project["id"]))
    data = {
        "db_path": str(DB_PATH),
        "project": {
            "id": project["id"],
            "name": project["name"],
            "root_path_display": project["root_path_display"],
            "git_branch": project["git_branch"],
        },
        "platform": platform_facts(),
        "latest_passport": bool(passport),
        "attempt_count": counts["attempts"],
        "context_decisions_count": counts["context_decisions"],
        "active_decisions_count": counts["active_decisions"],
        "pending_candidates_count": counts["pending_candidates"],
        "capture_events_count": counts["capture_events"],
        "seeded_decisions_count": len(seeded),
        "degraded_warnings": [],
    }
    con.close()
    if args.json:
        print_json(data)
    else:
        print("LBrain status")
        print(f"DB: {data['db_path']}")
        print(f"Project: {project['name']} ({project['root_path_display']})")
        print(f"Platform: {data['platform']['os']} / {data['platform']['shell_mode']}")
        print(f"Latest passport: {'yes' if data['latest_passport'] else 'no'}")
        print(f"Failed attempts: {data['attempt_count']}")
        print(f"Active decisions: {data['active_decisions_count']}")
        print(f"Pending candidates: {data['pending_candidates_count']}")
        print(f"Capture events: {data['capture_events_count']}")
        print(f"Context decisions: {data['context_decisions_count']}")
        if data["degraded_warnings"]:
            print("Warnings: " + "; ".join(data["degraded_warnings"]))
    return 0


def cmd_doctor(args):
    result = run_doctor()
    if args.json:
        print_json(result)
    else:
        print(render_doctor(result))
    return 0 if result["status"] in ("pass", "warn") else 4


def cmd_passport(args):
    con = connect()
    project = ensure_project(con)
    passport = get_or_refresh_passport(con, project, refresh=args.refresh)
    con.close()
    if args.json:
        print_json({"project": {"id": project["id"], "name": project["name"]}, "passport": passport})
    elif args.for_tool:
        print(passport_context(passport, args.for_tool))
    else:
        print(passport_summary(passport))
    return 0


def cmd_attempts_add(args):
    con = connect()
    project = ensure_project(con)
    try:
        attempt = add_attempt(
            con,
            project["id"],
            attempted_action=args.action,
            command=args.command,
            files_touched=args.file or [],
            error_summary=args.error,
            root_cause=args.root_cause,
            why_failed=args.why_failed,
            replacement_approach=args.replacement,
            platform=args.platform or platform_facts()["os"],
            retry_policy=args.retry_policy,
            confidence=args.confidence,
            source_session_id=args.session_id,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        con.close()
        return 1
    con.close()
    if args.json:
        print_json(attempt)
    else:
        print(f"Added failed attempt {attempt['id']}: {attempt['attempted_action']}")
    return 0


def cmd_attempts_list(args):
    con = connect()
    project = ensure_project(con)
    items = list_attempts(con, project["id"], limit=args.limit)
    con.close()
    if args.json:
        print_json({"attempts": items})
    else:
        print(render_attempts(items))
    return 0


def cmd_attempts_search(args):
    con = connect()
    project = ensure_project(con)
    items = search_attempts(con, project["id"], " ".join(args.query), limit=args.limit)
    con.close()
    if args.json:
        print_json({"attempts": items, "query": " ".join(args.query)})
    else:
        print(render_attempts(items))
    return 0


def cmd_context(args):
    con = connect()
    project = ensure_project(con)
    result = build_context(
        con,
        project,
        target=args.for_tool or "codex",
        query=args.query,
        explain=args.explain or args.debug,
        debug=args.debug,
        json_mode=args.json,
    )
    con.close()
    if args.json:
        print_json(result)
    else:
        print(result)
    return 0


def cmd_decisions_add(args):
    con = connect()
    project = ensure_project(con)
    try:
        decision = add_decision(
            con,
            project["id"],
            key=args.key,
            title=args.title,
            decision=args.decision,
            rationale=args.rationale,
            enforcement_hint=args.enforcement_hint,
            applies_to=args.applies_to or [],
            forbidden_patterns=args.forbidden_pattern or [],
            required_patterns=args.required_pattern or [],
            evidence={"source": "lstack brain decisions add"},
            source=args.source,
            confidence=args.confidence,
            privacy_class=args.privacy_class,
            scope=args.scope,
        )
    except ValueError as exc:
        con.close()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    con.close()
    if args.json:
        print_json({"decision": decision})
    else:
        print(f"Saved decision {decision['key']}: {decision['title']}")
    return 0


def cmd_decisions_list(args):
    con = connect()
    project = ensure_project(con)
    seed_lstack_default_decisions(con, project)
    project_id = None if args.scope == "user-global" else project["id"]
    items = list_decisions(con, project_id, status=args.status, limit=args.limit, scope=args.scope)
    con.close()
    if args.json:
        print_json({"decisions": items})
    else:
        print(render_decisions(items))
    return 0


def cmd_decisions_search(args):
    query = " ".join(args.query)
    con = connect()
    project = ensure_project(con)
    project_id = None if args.scope == "user-global" else project["id"]
    items = search_decisions(con, project_id, query, limit=args.limit, scope=args.scope)
    con.close()
    if args.json:
        print_json({"query": query, "decisions": items})
    else:
        print(render_decisions(items))
    return 0


def cmd_decisions_show(args):
    con = connect()
    project = ensure_project(con)
    project_id = None if args.scope == "user-global" else project["id"]
    item = get_decision(con, project_id, args.key, scope=args.scope)
    con.close()
    if not item:
        print(f"Decision not found: {args.key}", file=sys.stderr)
        return 1
    if args.json:
        print_json({"decision": item})
    else:
        print(render_decisions([item]))
    return 0


def cmd_decisions_check(args):
    con = connect()
    project = ensure_project(con)
    result = check_decisions(con, project, key=args.key, record_regressions=True)
    con.close()
    if args.json:
        print_json(result)
    else:
        print(render_check_result(result))
    return 0


def cmd_decisions_disable(args):
    con = connect()
    project = ensure_project(con)
    project_id = None if args.scope == "user-global" else project["id"]
    item = disable_decision(con, project_id, args.key, scope=args.scope)
    con.close()
    if not item:
        print(f"Decision not found: {args.key}", file=sys.stderr)
        return 1
    if args.json:
        print_json({"decision": item})
    else:
        print(f"Disabled decision {item['key']}")
    return 0


def _parse_evidence(values):
    evidence = {}
    for value in values or []:
        if "=" in value:
            key, raw = value.split("=", 1)
            evidence[key] = raw
    return evidence


def cmd_capture_status(args):
    con = connect()
    project = ensure_project(con)
    data = capture_status(con, project["id"])
    al_config = autolearn_config()
    con.close()
    data["auto_learn_enabled"] = al_config["auto_learn_enabled"]
    data["auto_promote_enabled"] = al_config["auto_promote_enabled"]
    if args.json:
        print_json(data)
    else:
        print("LBrain capture status")
        print(f"Auto-learning: {'enabled' if al_config['auto_learn_enabled'] else 'disabled'}")
        print(f"Auto-promotion: {'enabled' if al_config['auto_promote_enabled'] else 'disabled'}")
        print(f"Events: {data['events']}")
        print(f"Pending candidates: {data['pending_candidates']}")
        print(f"Approved candidates: {data['approved_candidates']}")
        print(f"Promoted candidates: {data['promoted_candidates']}")
        print(f"Rejected or stale candidates: {data['rejected_or_stale_candidates']}")
    return 0


def cmd_capture_event(args):
    evidence = _parse_evidence(args.evidence)
    if args.related_command:
        evidence["related_command_fingerprint"] = command_fingerprint(args.related_command)
    if args.related_fingerprint:
        evidence["related_command_fingerprint"] = args.related_fingerprint
    con = connect()
    project = ensure_project(con)
    try:
        result = record_event(
            con,
            project["id"],
            event_type=args.type,
            summary=args.summary,
            source=args.source,
            command=args.command,
            session_id=args.session_id,
            path=args.path,
            evidence=evidence,
            confidence_delta=args.confidence_delta,
        )
    except ValueError as exc:
        con.close()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    con.close()
    if args.json:
        print_json(result)
    else:
        print(f"Recorded event {result['event']['id']}: {result['event']['event_type']}")
        if result.get("candidate"):
            candidate = result["candidate"]
            print(f"Candidate {candidate['id']}: {candidate['title']} ({candidate['status']}, confidence {candidate['confidence']}/10)")
    return 0


def cmd_capture_events(args):
    con = connect()
    project = ensure_project(con)
    items = list_events(con, project["id"], limit=args.limit, event_type=args.type)
    con.close()
    if args.json:
        print_json({"events": items})
    else:
        print(render_events(items))
    return 0


def cmd_capture_explain_event(args):
    con = connect()
    project = ensure_project(con)
    result = explain_event(con, project["id"], args.id)
    con.close()
    if not result:
        print(f"Event not found: {args.id}", file=sys.stderr)
        return 1
    if args.json:
        print_json(result)
    else:
        evt = result["event"]
        print(f"Event {evt['id']}: {evt['event_type']} ({evt['source']})")
        print(f"Summary: {evt['summary']}")
        print(f"Redaction: {evt['redaction_status']}")
        if evt.get("command_preview_redacted"):
            print(f"Command: {evt['command_preview_redacted']}")
        candidates = result.get("related_candidates", [])
        if candidates:
            print(f"Related candidates ({len(candidates)}):")
            for c in candidates:
                print(f"  [{c['id']}] {c['title']} status={c['status']} confidence={c['confidence']}/10")
        else:
            print("Related candidates: none")
    return 0


def cmd_capture_undo(args):
    con = connect()
    project = ensure_project(con)
    try:
        result = undo_event(con, project["id"], args.id)
    except ValueError as exc:
        con.close()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    con.close()
    if args.json:
        print_json(result)
    else:
        undone = result.get("undone", [])
        if undone:
            print(f"Undone {len(undone)} item(s) linked to event {args.id}:")
            for u in undone:
                print(f"  candidate {u['candidate_id']}: {u['action']}")
        else:
            print(f"No auto-promoted items found for event {args.id}.")
    return 0


def cmd_capture_autolearn(args):
    config = autolearn_config()
    if args.json:
        print_json(config)
    else:
        print("LBrain auto-learn config")
        print(f"Auto-learning: {'enabled' if config['auto_learn_enabled'] else 'disabled'} (LSTACK_BRAIN_AUTO_LEARN)")
        print(f"Auto-promotion: {'enabled' if config['auto_promote_enabled'] else 'disabled'} (LSTACK_BRAIN_AUTO_PROMOTE)")
        print(f"Max output preview: {config['max_output_preview']} chars (LSTACK_BRAIN_AUTO_LEARN_MAX_OUTPUT_PREVIEW)")
        max_ev = config['max_events_per_session']
        print(f"Max events/session: {'unlimited' if max_ev is None else max_ev} (LSTACK_BRAIN_AUTO_LEARN_MAX_EVENTS_PER_SESSION)")
        print(f"Debug logging: {'on' if config['debug'] else 'off'} (LSTACK_BRAIN_AUTO_LEARN_DEBUG)")
    return 0


def cmd_capture_candidates(args):
    con = connect()
    project = ensure_project(con)
    items = list_candidates(con, project["id"], status=args.status, limit=args.limit)
    con.close()
    if args.json:
        print_json({"candidates": items})
    else:
        print(render_candidates(items))
    return 0


def cmd_capture_approve(args):
    con = connect()
    project = ensure_project(con)
    item = approve_candidate(con, project["id"], args.id)
    con.close()
    if not item:
        print(f"Candidate not found: {args.id}", file=sys.stderr)
        return 1
    if args.json:
        print_json({"candidate": item})
    else:
        print(f"Approved candidate {item['id']}: {item['title']}")
    return 0


def cmd_capture_reject(args):
    con = connect()
    project = ensure_project(con)
    item = reject_candidate(con, project["id"], args.id, reason=args.reason)
    con.close()
    if not item:
        print(f"Candidate not found: {args.id}", file=sys.stderr)
        return 1
    if args.json:
        print_json({"candidate": item})
    else:
        print(f"Rejected candidate {item['id']}: {item['title']}")
    return 0


def cmd_capture_promote(args):
    con = connect()
    project = ensure_project(con)
    try:
        result = promote_candidate(con, project["id"], args.id)
    except ValueError as exc:
        con.close()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    con.close()
    if args.json:
        print_json(result)
    else:
        candidate = result["candidate"] if isinstance(result, dict) else result
        promoted = result.get("promoted") if isinstance(result, dict) else None
        if promoted:
            print(f"Promoted candidate {candidate['id']} to {promoted['type']}:{promoted['id']}")
        else:
            print(f"Approved candidate {candidate['id']}")
    return 0


def cmd_capture_explain(args):
    con = connect()
    project = ensure_project(con)
    item = get_candidate(con, project["id"], args.id)
    con.close()
    if not item:
        print(f"Candidate not found: {args.id}", file=sys.stderr)
        return 1
    if args.json:
        print_json({"candidate": item})
    else:
        print(explain_candidate(item))
    return 0


def cmd_contract_create(args):
    con = connect()
    project = ensure_project(con)
    try:
        contract = create_contract(
            con,
            project["id"],
            task_goal=args.goal,
            title=args.title,
            mode=args.mode,
            allowed_files=args.allow or [],
            forbidden_files=args.deny or [],
            allowed_commands=args.allow_command or [],
            forbidden_commands=args.deny_command or [],
            max_files_changed=args.max_files,
            max_lines_changed=args.max_lines,
            required_tests=args.required_test or [],
            stop_conditions=args.stop_condition or [],
            review_checklist=args.review_check or [],
            replace=args.replace,
        )
    except ValueError as exc:
        con.close()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    con.close()
    if args.json:
        print_json({"contract": contract})
    else:
        print(render_contract_status(contract))
    return 0


def cmd_contract_status(args):
    con = connect()
    project = ensure_project(con)
    contract = get_active_contract(con, project["id"])
    events = get_recent_events(con, contract["id"]) if contract else []
    con.close()
    if args.json:
        print_json({"active_contract": contract, "recent_events": events})
    else:
        print(render_contract_status(contract, events))
    return 0


def cmd_contract_list(args):
    con = connect()
    project = ensure_project(con)
    items = list_contracts(con, project["id"], status=args.status, limit=args.limit if args.limit else 20)
    con.close()
    if args.json:
        print_json({"contracts": items})
    else:
        if not items:
            print("No contracts found.")
        else:
            for c in items:
                title_part = f" - {c['title']}" if c.get("title") else ""
                print(f"#{c['id']}{title_part} [{c['status']}] mode={c['mode']}: {c['task_goal'][:60]}")
    return 0


def cmd_contract_show(args):
    con = connect()
    project = ensure_project(con)
    contract = get_contract(con, args.id)
    if not contract or contract["project_id"] != project["id"]:
        con.close()
        print(f"Contract not found: {args.id}", file=sys.stderr)
        return 1
    events = get_recent_events(con, args.id)
    con.close()
    if args.json:
        print_json({"contract": contract, "recent_events": events})
    else:
        print(render_contract_status(contract, events))
    return 0


def cmd_contract_check(args):
    con = connect()
    project = ensure_project(con)
    contract = get_active_contract(con, project["id"])
    if not contract:
        con.close()
        if args.json:
            print_json({"status": "pass", "message": "No active contract."})
        else:
            print("No active contract. Nothing to check.")
        return 0
    result = run_contract_check(
        con,
        contract,
        project_root=project.get("root"),
        paths=args.path or [],
        commands=args.command or [],
        check_changed=args.changed_files,
    )
    con.close()
    if args.json:
        print_json(result)
    else:
        print(render_contract_check_result(result))
    if result["status"] == "violation" and (args.strict_exit or contract["mode"] == "strict"):
        return 10
    if result.get("degraded") and not result["violations"] and not result["warnings"]:
        return 20
    return 0


def cmd_contract_close(args):
    con = connect()
    project = ensure_project(con)
    contract_id = args.id
    if not contract_id:
        active = get_active_contract(con, project["id"])
        if not active:
            con.close()
            print("No active contract to close.", file=sys.stderr)
            return 1
        contract_id = active["id"]
    contract = close_contract(con, contract_id, project["id"], reason=args.reason)
    con.close()
    if not contract:
        print(f"Contract not found: {contract_id}", file=sys.stderr)
        return 1
    if args.json:
        print_json({"contract": contract})
    else:
        print(f"Closed contract #{contract['id']}: {contract['task_goal'][:60]}")
    return 0


def cmd_contract_complete(args):
    con = connect()
    project = ensure_project(con)
    contract_id = args.id
    if not contract_id:
        active = get_active_contract(con, project["id"])
        if not active:
            con.close()
            print("No active contract to complete.", file=sys.stderr)
            return 1
        contract_id = active["id"]
    contract, warnings = complete_contract(con, contract_id, project["id"], reason=args.reason)
    con.close()
    if not contract:
        print(f"Contract not found: {contract_id}", file=sys.stderr)
        return 1
    if args.json:
        print_json({"contract": contract, "warnings": warnings})
    else:
        print(f"Completed contract #{contract['id']}: {contract['task_goal'][:60]}")
        for w in warnings:
            print(f"Warning: {w}")
    return 0


def cmd_contract_explain(args):
    con = connect()
    project = ensure_project(con)
    contract = get_active_contract(con, project["id"])
    con.close()
    if not contract:
        if args.json:
            print_json({"message": "No active contract."})
        else:
            print("No active contract.")
        return 0
    text = explain_contract(
        contract,
        path=args.path,
        command=args.command,
        project_root=project.get("root"),
    )
    if args.json:
        print_json({"explanation": text, "contract_id": contract["id"]})
    else:
        print(text)
    return 0


def cmd_contract_record_test(args):
    con = connect()
    project = ensure_project(con)
    contract = get_active_contract(con, project["id"])
    if not contract:
        con.close()
        print("No active contract.", file=sys.stderr)
        return 1
    updated = record_test(
        con,
        contract["id"],
        project["id"],
        command=args.command,
        result=args.result,
        summary=args.summary,
    )
    con.close()
    if args.json:
        print_json({"contract": updated})
    else:
        print(f"Recorded test [{args.result}]: {args.command[:60] if args.command else '(no command)'}")
    return 0


def _receipt_error(exc):
    print(f"Error: {exc}", file=sys.stderr)
    return 1


def cmd_receipt_start(args):
    con = connect()
    project = ensure_project(con)
    try:
        receipt = start_receipt(
            con,
            project,
            title=args.title,
            goal=args.goal,
            contract_id=args.contract,
            replace=args.replace,
            allow_multiple=args.allow_multiple,
            source="manual",
        )
    except (ValueError, GitReceiptError) as exc:
        con.close()
        return _receipt_error(exc)
    con.close()
    if args.json:
        print_json({"receipt": receipt})
    else:
        print(f"Started receipt #{receipt['id']}: {receipt.get('title') or '(untitled)'}")
        print(f"Git: {receipt['branch'] or '-'} @ {receipt['base_commit'][:12]}")
        if receipt.get("contract_id"):
            print(f"Linked contract: #{receipt['contract_id']}")
    return 0


def cmd_receipt_status(args):
    con = connect()
    project = ensure_project(con)
    try:
        data = receipt_status(con, project, require_current_git=True)
    except (ValueError, GitReceiptError) as exc:
        con.close()
        return _receipt_error(exc)
    con.close()
    if args.json:
        print_json(data)
    else:
        print(render_receipt_status(data))
    return 0


def cmd_receipt_list(args):
    con = connect()
    project = ensure_project(con)
    try:
        items = list_receipts(con, project["id"], status=args.status, limit=args.limit)
    except ValueError as exc:
        con.close()
        return _receipt_error(exc)
    con.close()
    if args.json:
        print_json({"receipts": items})
    else:
        print(render_receipt_list(items))
    return 0


def cmd_receipt_show(args):
    con = connect()
    project = ensure_project(con)
    receipt = get_receipt(con, project["id"], args.id)
    events = list_receipt_events(con, project["id"], args.id, limit=50) if receipt else []
    con.close()
    if not receipt:
        print(f"Receipt not found: {args.id}", file=sys.stderr)
        return 1
    if args.json:
        print_json({"receipt": receipt, "events": events})
    else:
        print(render_receipt_show(receipt, events))
    return 0


def cmd_receipt_finalize(args):
    con = connect()
    project = ensure_project(con)
    try:
        receipt = finalize_receipt(con, project, receipt_id=args.id, summary=args.summary)
    except (ValueError, GitReceiptError) as exc:
        con.close()
        return _receipt_error(exc)
    con.close()
    if args.json:
        print_json({"receipt": receipt})
    else:
        print(f"Finalized receipt #{receipt['id']}: {receipt.get('summary') or receipt.get('title') or '(untitled)'}")
        print(f"Head: {receipt.get('head_commit') or '-'}")
        print(f"Changed files: {len(receipt.get('files_changed') or [])}")
    return 0


def cmd_receipt_abandon(args):
    con = connect()
    project = ensure_project(con)
    try:
        receipt = abandon_receipt(con, project["id"], receipt_id=args.id, reason=args.reason)
    except ValueError as exc:
        con.close()
        return _receipt_error(exc)
    con.close()
    if args.json:
        print_json({"receipt": receipt})
    else:
        print(f"Abandoned receipt #{receipt['id']}: {receipt.get('summary') or ''}".rstrip())
    return 0


def cmd_receipt_attach_event(args):
    con = connect()
    project = ensure_project(con)
    try:
        receipt = attach_capture_event(con, project["id"], args.capture_event, receipt_id=args.receipt)
    except ValueError as exc:
        con.close()
        return _receipt_error(exc)
    con.close()
    if args.json:
        print_json({"receipt": receipt})
    else:
        print(f"Attached capture event #{args.capture_event} to receipt #{receipt['id']}")
    return 0


def cmd_receipt_record_command(args):
    con = connect()
    project = ensure_project(con)
    try:
        receipt = receipt_record_command(con, project["id"], args.command, result=args.result)
    except ValueError as exc:
        con.close()
        return _receipt_error(exc)
    con.close()
    if args.json:
        print_json({"receipt": receipt})
    else:
        print(f"Recorded command on receipt #{receipt['id']}: {args.result}")
    return 0


def cmd_receipt_record_test(args):
    con = connect()
    project = ensure_project(con)
    try:
        receipt = receipt_record_test(con, project["id"], args.command, result=args.result)
    except ValueError as exc:
        con.close()
        return _receipt_error(exc)
    con.close()
    if args.json:
        print_json({"receipt": receipt})
    else:
        print(f"Recorded test on receipt #{receipt['id']}: {args.result}")
    return 0


def cmd_receipt_explain(args):
    con = connect()
    project = ensure_project(con)
    data = explain_receipt(con, project, receipt_id=args.id)
    con.close()
    if args.json:
        print_json(data)
    else:
        print(render_receipt_explain(data))
    return 0


def cmd_receipt_undo_hint(args):
    con = connect()
    project = ensure_project(con)
    if args.id:
        receipt = get_receipt(con, project["id"], args.id)
    else:
        open_items = list_receipts(con, project["id"], status="open", limit=1)
        receipt = open_items[0] if open_items else (list_receipts(con, project["id"], limit=1)[0] if list_receipts(con, project["id"], limit=1) else None)
    con.close()
    if not receipt:
        print("No receipt found.", file=sys.stderr)
        return 1
    print(receipt.get("undo_hint") or "Use git diff and git diff --stat to inspect changes before undoing anything.")
    return 0


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def cmd_overview(args):
    con = connect()
    project = ensure_project(con)
    seed_lstack_default_decisions(con, project)
    target = getattr(args, "for_tool", None) or "claude"
    query = getattr(args, "query", None)
    data = build_overview(con, project, target=target, query=query)
    con.close()
    if args.json:
        print_json(data)
    else:
        fw = data["firewall"]
        gov = data["context_governor"]
        cap = data["capture"]
        print("LBrain overview")
        print(f"Project: {data['project']['name']} on {data['project']['git_branch'] or 'unknown'}")
        print(f"Platform: {data['platform']['os']} / {data['platform']['shell_mode']}")
        print(f"Repo Passport: {'yes' if data['passport']['available'] else 'no'}")
        print(f"Open Change Receipt: {data['receipts']['open']['id'] if data['receipts']['open'] else 'none'}")
        print(f"Active Task Contract: {data['contracts']['active']['id'] if data['contracts']['active'] else 'none'}")
        print(f"AI Mistake Firewall: {fw['status']}")
        print(f"Context Governor: {gov['included_count']} included, {gov['skipped_count']} skipped")
        print(f"Decisions: {data['decisions']['active_count']} active")
        print(f"Failed attempts: {data['failed_attempts']['count']}")
        print(f"Capture: {cap['events_count']} events, {cap['pending_candidates_count']} pending candidates")
        print(f"Doctor: {data['doctor']['status']}")
    return 0


# ---------------------------------------------------------------------------
# Firewall commands
# ---------------------------------------------------------------------------

def cmd_firewall_status(args):
    con = connect()
    project = ensure_project(con)
    data = firewall_status(con, project)
    con.close()
    if args.json:
        print_json(data)
    else:
        print(render_firewall_status(data))
    return 0


def cmd_firewall_check(args):
    con = connect()
    project = ensure_project(con)
    result = run_firewall_check(
        command=args.command,
        paths=args.path or [],
        changed_files=args.changed_file or [],
        tool=args.tool,
        con=con,
        project=project,
    )
    con.close()
    if args.json:
        print_json(result)
    else:
        print(render_firewall_check(result, verbose=True))
    high_warnings = [w for w in result["warnings"] if w["severity"] == "high" and w.get("strict_exit_block")]
    if args.strict_exit and high_warnings:
        return 2
    return 0


def cmd_firewall_explain(args):
    con = connect()
    project = ensure_project(con)
    data = firewall_explain(con, project)
    con.close()
    if args.json:
        print_json(data)
    else:
        print("AI Mistake Firewall — active rules and sources")
        print(f"Total rules: {data['rule_count']}")
        for src in data["sources"]:
            print(f"  {src['name']}: {src['description']}")
        if data.get("active_decisions"):
            print(f"Active decisions contributing: {len(data['active_decisions'])}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="lstack brain")
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("doctor")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("passport")
    p.add_argument("--json", action="store_true")
    p.add_argument("--refresh", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--for", dest="for_tool", choices=("claude", "codex"))
    p.set_defaults(func=cmd_passport)

    p = sub.add_parser("context")
    p.add_argument("--json", action="store_true")
    p.add_argument("--for", dest="for_tool", choices=("claude", "codex", "chatgpt"))
    p.add_argument("--explain", action="store_true")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--query")
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("overview")
    p.add_argument("--json", action="store_true")
    p.add_argument("--for", dest="for_tool", choices=("claude", "codex", "chatgpt", "generic"))
    p.add_argument("--query")
    p.set_defaults(func=cmd_overview)

    firewall = sub.add_parser("firewall")
    firewall_sub = firewall.add_subparsers(dest="firewall_cmd")

    p = firewall_sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_firewall_status)

    p = firewall_sub.add_parser("check")
    p.add_argument("--command")
    p.add_argument("--path", action="append", metavar="PATH")
    p.add_argument("--changed-file", action="append", metavar="PATH")
    p.add_argument("--tool", choices=("Bash", "Write", "Edit", "MultiEdit"))
    p.add_argument("--strict-exit", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_firewall_check)

    p = firewall_sub.add_parser("explain")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_firewall_explain)

    decisions = sub.add_parser("decisions")
    decisions_sub = decisions.add_subparsers(dest="decisions_cmd")

    p = decisions_sub.add_parser("add")
    p.add_argument("--key", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--decision", required=True)
    p.add_argument("--rationale")
    p.add_argument("--enforcement-hint")
    p.add_argument("--forbidden-pattern", action="append")
    p.add_argument("--required-pattern", action="append")
    p.add_argument("--applies-to", action="append")
    p.add_argument("--confidence", type=int, default=8)
    p.add_argument("--source", default="manual")
    p.add_argument("--scope", default="project", choices=("project", "user-global", "template", "test-fixture"))
    p.add_argument("--privacy-class", default="local-only", choices=("local-only", "exportable", "sync-allowed", "never-export"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_decisions_add)

    p = decisions_sub.add_parser("list")
    p.add_argument("--status", choices=("active", "superseded", "disabled"))
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--scope", default="project", choices=("project", "user-global", "template", "test-fixture"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_decisions_list)

    p = decisions_sub.add_parser("search")
    p.add_argument("query", nargs="+")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--scope", default="project", choices=("project", "user-global", "template", "test-fixture"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_decisions_search)

    p = decisions_sub.add_parser("show")
    p.add_argument("key")
    p.add_argument("--scope", default="project", choices=("project", "user-global", "template", "test-fixture"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_decisions_show)

    p = decisions_sub.add_parser("check")
    p.add_argument("--key")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_decisions_check)

    p = decisions_sub.add_parser("disable")
    p.add_argument("key")
    p.add_argument("--scope", default="project", choices=("project", "user-global", "template", "test-fixture"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_decisions_disable)

    capture = sub.add_parser("capture")
    capture_sub = capture.add_subparsers(dest="capture_cmd")

    p = capture_sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_status)

    p = capture_sub.add_parser("events")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--type", dest="type", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_events)

    p = capture_sub.add_parser("explain-event")
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_explain_event)

    p = capture_sub.add_parser("undo")
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_undo)

    p = capture_sub.add_parser("autolearn")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_autolearn)

    p = capture_sub.add_parser("event")
    p.add_argument("--type", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--command")
    p.add_argument("--source", default="manual")
    p.add_argument("--session-id")
    p.add_argument("--path")
    p.add_argument("--evidence", action="append", help="Evidence as key=value")
    p.add_argument("--related-command")
    p.add_argument("--related-fingerprint")
    p.add_argument("--confidence-delta", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_event)

    p = capture_sub.add_parser("candidates")
    p.add_argument("--status", default="pending", choices=("pending", "active", "approved", "rejected", "promoted", "superseded", "stale"))
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_candidates)

    p = capture_sub.add_parser("approve")
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_approve)

    p = capture_sub.add_parser("reject")
    p.add_argument("id", type=int)
    p.add_argument("--reason")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_reject)

    p = capture_sub.add_parser("promote")
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_promote)

    p = capture_sub.add_parser("explain")
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture_explain)

    contract = sub.add_parser("contract")
    contract_sub = contract.add_subparsers(dest="contract_cmd")

    p = contract_sub.add_parser("create")
    p.add_argument("--goal", required=True)
    p.add_argument("--title")
    p.add_argument("--allow", action="append", metavar="PATTERN")
    p.add_argument("--deny", action="append", metavar="PATTERN")
    p.add_argument("--allow-command", action="append", metavar="PATTERN")
    p.add_argument("--deny-command", action="append", metavar="PATTERN")
    p.add_argument("--required-test", action="append", metavar="COMMAND")
    p.add_argument("--stop-condition", action="append", metavar="TEXT")
    p.add_argument("--review-check", action="append", metavar="TEXT")
    p.add_argument("--max-files", type=int)
    p.add_argument("--max-lines", type=int)
    p.add_argument("--mode", default="warn", choices=("off", "warn", "strict"))
    p.add_argument("--replace", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_contract_create)

    p = contract_sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_contract_status)

    p = contract_sub.add_parser("list")
    p.add_argument("--all", action="store_true", dest="all_contracts")
    p.add_argument("--status", choices=("active", "closed", "completed", "violated", "draft", "expired"))
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_contract_list)

    p = contract_sub.add_parser("show")
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_contract_show)

    p = contract_sub.add_parser("check")
    p.add_argument("--path", action="append", metavar="PATH")
    p.add_argument("--command", action="append", metavar="COMMAND")
    p.add_argument("--changed-files", action="store_true")
    p.add_argument("--strict-exit", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_contract_check)

    p = contract_sub.add_parser("close")
    p.add_argument("--id", type=int)
    p.add_argument("--reason")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_contract_close)

    p = contract_sub.add_parser("complete")
    p.add_argument("--id", type=int)
    p.add_argument("--reason")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_contract_complete)

    p = contract_sub.add_parser("explain")
    p.add_argument("--path", metavar="PATH")
    p.add_argument("--command", metavar="COMMAND")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_contract_explain)

    p = contract_sub.add_parser("record-test")
    p.add_argument("--command", metavar="COMMAND")
    p.add_argument("--result", default="unknown", choices=("pass", "fail", "unknown"))
    p.add_argument("--summary")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_contract_record_test)

    receipt = sub.add_parser("receipt")
    receipt_sub = receipt.add_subparsers(dest="receipt_cmd")

    p = receipt_sub.add_parser("start")
    p.add_argument("--title")
    p.add_argument("--goal")
    p.add_argument("--contract", type=int)
    p.add_argument("--replace", action="store_true")
    p.add_argument("--allow-multiple", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_receipt_start)

    p = receipt_sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_receipt_status)

    p = receipt_sub.add_parser("list")
    p.add_argument("--status", choices=("open", "finalized", "abandoned"))
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_receipt_list)

    p = receipt_sub.add_parser("show")
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_receipt_show)

    p = receipt_sub.add_parser("finalize")
    p.add_argument("--id", type=int)
    p.add_argument("--summary")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_receipt_finalize)

    p = receipt_sub.add_parser("abandon")
    p.add_argument("--id", type=int)
    p.add_argument("--reason", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_receipt_abandon)

    p = receipt_sub.add_parser("attach-event")
    p.add_argument("--receipt", type=int)
    p.add_argument("--capture-event", type=int, required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_receipt_attach_event)

    p = receipt_sub.add_parser("record-command")
    p.add_argument("--command", required=True)
    p.add_argument("--result", default="unknown", choices=("pass", "fail", "unknown"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_receipt_record_command)

    p = receipt_sub.add_parser("record-test")
    p.add_argument("--command", required=True)
    p.add_argument("--result", default="unknown", choices=("pass", "fail", "unknown"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_receipt_record_test)

    p = receipt_sub.add_parser("explain")
    p.add_argument("--id", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_receipt_explain)

    p = receipt_sub.add_parser("undo-hint")
    p.add_argument("--id", type=int)
    p.set_defaults(func=cmd_receipt_undo_hint)

    attempts = sub.add_parser("attempts")
    attempts_sub = attempts.add_subparsers(dest="attempts_cmd")

    p = attempts_sub.add_parser("add")
    p.add_argument("--action", required=True)
    p.add_argument("--command")
    p.add_argument("--error")
    p.add_argument("--root-cause")
    p.add_argument("--why-failed")
    p.add_argument("--replacement")
    p.add_argument("--file", action="append")
    p.add_argument("--platform")
    p.add_argument("--retry-policy", default="ask", choices=("never", "ask", "after-change", "allowed"))
    p.add_argument("--confidence", type=int, default=7)
    p.add_argument("--session-id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_attempts_add)

    p = attempts_sub.add_parser("list")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_attempts_list)

    p = attempts_sub.add_parser("search")
    p.add_argument("query", nargs="+")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_attempts_search)

    return parser


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv[:2] == ["passport", "refresh"]:
        argv = ["passport", "--refresh"] + argv[2:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except sqlite3.Error as exc:
        print(f"DB error: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

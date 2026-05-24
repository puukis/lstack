#!/usr/bin/env python3
"""LBrain CLI."""

import argparse
import json
import sqlite3
import sys

from brain.attempts import add_attempt, list_attempts, render_attempts, search_attempts
from brain.capture import (
    approve_candidate,
    capture_status,
    explain_candidate,
    get_candidate,
    list_candidates,
    promote_candidate,
    record_event,
    reject_candidate,
    render_candidates,
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
from brain.doctor import render_doctor, run_doctor
from brain.passport import get_or_refresh_passport, passport_context, passport_summary
from brain.platform import platform_facts
from brain.attempts import command_fingerprint


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
    con.close()
    if args.json:
        print_json(data)
    else:
        print("LBrain capture status")
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

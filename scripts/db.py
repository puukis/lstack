#!/usr/bin/env python3
"""lstack persistent memory — all DB operations via subcommands."""

import sqlite3
import json
import sys
import os
import re
import argparse
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path.home() / ".claude" / "memory" / "lstack.db"

STOPWORDS = {
    "from", "import", "return", "const", "function", "class", "interface",
    "export", "default", "null", "true", "false", "this", "with", "then",
    "else", "when", "that", "have", "will", "your", "into", "been", "were",
    "them", "some", "what", "more", "also", "than", "just", "each", "make",
    "type", "void", "async", "await", "string", "number", "boolean",
}


def normalize_project(path):
    """Return a stable, cross-platform project path for DB storage."""
    if not path:
        return path
    # Convert git-bash style /c/Users/... -> C:/Users/...
    m = re.match(r'^/([a-zA-Z])/(.*)', path)
    if m:
        return f"{m.group(1).upper()}:/{m.group(2)}"
    # Normalize backslashes to forward slashes
    return path.replace('\\', '/')


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_keywords(text):
    # Insert space before uppercase letter following a lowercase letter (camelCase split)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    # Split on non-alphanumeric characters
    tokens = re.split(r"[/\\.\\-_ ()\[\]{};=><\!@#$%&*+,?\"']+", text)
    seen = set()
    result = []
    for tok in tokens:
        word = tok.lower()
        if len(word) >= 4 and word not in STOPWORDS and word not in seen:
            seen.add(word)
            result.append(word)
        if len(result) >= 6:
            break
    return result


def get_project(cwd=None):
    path = cwd or os.getcwd()
    try:
        import subprocess
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path, stderr=subprocess.DEVNULL
        ).decode().strip()
        return normalize_project(os.path.realpath(root))
    except Exception:
        return normalize_project(os.path.realpath(path))


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def check_fts5(con):
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_test USING fts5(x)")
        con.execute("DROP TABLE IF EXISTS _fts5_test")
        return True
    except Exception:
        return False


def init_db(con):
    fts5 = check_fts5(con)

    con.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            summary TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT
        );

        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            project TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            created_at TEXT NOT NULL
        );
    """)

    if fts5:
        con.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
                content,
                tags,
                content=observations,
                content_rowid=id
            );

            CREATE TRIGGER IF NOT EXISTS obs_ai AFTER INSERT ON observations BEGIN
                INSERT INTO observations_fts(rowid, content, tags)
                VALUES (new.id, new.content, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS obs_ad AFTER DELETE ON observations BEGIN
                INSERT INTO observations_fts(observations_fts, rowid, content, tags)
                VALUES ('delete', old.id, old.content, old.tags);
            END;
        """)

    con.commit()
    return fts5


def has_fts5(con):
    try:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='observations_fts'"
        ).fetchone()
        return row is not None
    except Exception:
        return False


def cmd_init(args):
    con = connect()
    init_db(con)
    con.close()
    print("ok")


def cmd_session_start(args):
    session_id = args.session_id
    project = normalize_project(args.project) if args.project else normalize_project(get_project())

    con = connect()
    init_db(con)

    # Insert session row (ignore if already exists)
    try:
        con.execute(
            "INSERT OR IGNORE INTO sessions (id, project, started_at) VALUES (?, ?, ?)",
            (session_id, project, iso_now())
        )
        con.commit()
    except Exception:
        pass

    # Project-scoped observations
    proj_rows = con.execute(
        "SELECT content, created_at, project FROM observations "
        "WHERE project = ? ORDER BY created_at DESC LIMIT 5",
        (project,)
    ).fetchall()

    # Global observations
    global_rows = con.execute(
        "SELECT content, created_at, project FROM observations "
        "WHERE project = 'global' ORDER BY created_at DESC LIMIT 5",
        ()
    ).fetchall()

    # Merge, deduplicate by content, cap at 5
    seen = set()
    lines = []
    for content, created_at, proj in proj_rows + global_rows:
        if content not in seen:
            seen.add(content)
            scope = "global" if proj == "global" else "project"
            date = created_at[:10] if created_at else ""
            c = content[:100] if content else ""
            lines.append(f"[{date}] [{scope}] {c}")
        if len(lines) >= 5:
            break

    con.close()

    context = "\n".join(lines)
    print(json.dumps({"context": context, "count": len(lines)}))


def cmd_session_end(args):
    session_id = args.session_id
    content = args.content
    tags = args.tags or ""
    project = get_project()

    con = connect()
    init_db(con)

    con.execute(
        "UPDATE sessions SET ended_at = ?, summary = ? WHERE id = ?",
        (iso_now(), content, session_id)
    )
    con.execute(
        "INSERT INTO observations (session_id, project, content, tags, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, project, content, tags[:200], iso_now())
    )
    con.commit()
    con.close()
    print("ok")


def cmd_observe(args):
    session_id = args.session_id
    project = normalize_project(args.project) if args.project else normalize_project(get_project())
    content = args.content
    tags = args.tags or ""

    # Clamp tags: max 10, each max 20 chars
    tag_list = [t[:20] for t in tags.split(",") if t.strip()][:10]
    tags_str = ",".join(tag_list)

    con = connect()
    init_db(con)

    cur = con.execute(
        "INSERT INTO observations (session_id, project, content, tags, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, project, content, tags_str, iso_now())
    )
    con.commit()
    row_id = cur.lastrowid
    con.close()
    print(f"ok {row_id}")


def cmd_search(args):
    query = args.query
    project = os.path.realpath(args.project) if args.project else None
    limit = min(args.limit or 2, 5)

    con = connect()
    init_db(con)
    fts = has_fts5(con)

    results = []
    try:
        if fts:
            if project:
                rows = con.execute(
                    """SELECT o.content, o.project, o.created_at, o.tags
                       FROM observations_fts f
                       JOIN observations o ON o.id = f.rowid
                       WHERE observations_fts MATCH ?
                       AND (o.project = ? OR o.project = 'global')
                       ORDER BY rank LIMIT ?""",
                    (query, project, limit)
                ).fetchall()
            else:
                rows = con.execute(
                    """SELECT o.content, o.project, o.created_at, o.tags
                       FROM observations_fts f
                       JOIN observations o ON o.id = f.rowid
                       WHERE observations_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (query, limit)
                ).fetchall()
        else:
            print("FTS5 unavailable, using LIKE search (slower)", file=sys.stderr)
            # Build LIKE conditions for each keyword
            keywords = query.replace(",", " ").split()
            if keywords:
                kw = keywords[0]
                like = f"%{kw}%"
                if project:
                    rows = con.execute(
                        "SELECT content, project, created_at, tags FROM observations "
                        "WHERE (content LIKE ? OR tags LIKE ?) "
                        "AND (project = ? OR project = 'global') "
                        "ORDER BY created_at DESC LIMIT ?",
                        (like, like, project, limit)
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT content, project, created_at, tags FROM observations "
                        "WHERE content LIKE ? OR tags LIKE ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (like, like, limit)
                    ).fetchall()
            else:
                rows = []

        for content, proj, created_at, tags in rows:
            results.append({
                "content": content,
                "project": proj,
                "created_at": created_at,
                "tags": tags or "",
            })
    except Exception:
        results = []

    con.close()
    print(json.dumps(results))


def cmd_stats(args):
    project = normalize_project(get_project())

    con = connect()
    init_db(con)

    size_kb = DB_PATH.stat().st_size // 1024 if DB_PATH.exists() else 0

    total_sessions = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    proj_sessions = con.execute("SELECT COUNT(*) FROM sessions WHERE project = ?", (project,)).fetchone()[0]

    total_obs = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    proj_obs = con.execute("SELECT COUNT(*) FROM observations WHERE project = ?", (project,)).fetchone()[0]

    oldest = con.execute("SELECT MIN(created_at) FROM observations").fetchone()[0] or "none"
    newest = con.execute("SELECT MAX(created_at) FROM observations").fetchone()[0] or "none"

    con.close()

    print(f"DB path: {DB_PATH} ({size_kb} KB)")
    print(f"Sessions: {total_sessions} ({proj_sessions} this project)")
    print(f"Observations: {total_obs} ({proj_obs} this project)")
    print(f"Oldest entry: {oldest[:10] if oldest != 'none' else oldest}")
    print(f"Newest entry: {newest[:10] if newest != 'none' else newest}")


def cmd_forget(args):
    query = args.query
    con = connect()
    init_db(con)
    fts = has_fts5(con)

    results = []
    try:
        if fts:
            rows = con.execute(
                """SELECT o.id, o.content, o.created_at, o.project
                   FROM observations_fts f
                   JOIN observations o ON o.id = f.rowid
                   WHERE observations_fts MATCH ?
                   ORDER BY rank LIMIT 10""",
                (query,)
            ).fetchall()
        else:
            like = f"%{query}%"
            rows = con.execute(
                "SELECT id, content, created_at, project FROM observations "
                "WHERE content LIKE ? OR tags LIKE ? ORDER BY created_at DESC LIMIT 10",
                (like, like)
            ).fetchall()
        for row_id, content, created_at, project in rows:
            results.append({"id": row_id, "content": content,
                            "created_at": created_at, "project": project})
    except Exception:
        results = []

    if not results:
        print(json.dumps({"deleted": 0, "message": f"No observations matched '{query}'"}))
        con.close()
        return

    ids = [r["id"] for r in results]
    placeholders = ",".join("?" * len(ids))
    con.execute(f"DELETE FROM observations WHERE id IN ({placeholders})", ids)
    con.commit()

    if fts:
        try:
            con.execute("INSERT INTO observations_fts(observations_fts) VALUES ('rebuild')")
            con.commit()
        except Exception:
            pass

    con.close()
    deleted_contents = [r["content"][:80] for r in results]
    print(json.dumps({"deleted": len(ids), "removed": deleted_contents}))


def cmd_prune(args):
    days = args.days or 90
    cutoff = datetime.now(timezone.utc)
    # Simple date math: subtract days
    import time
    cutoff_str = datetime.fromtimestamp(
        time.time() - days * 86400, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    con = connect()
    init_db(con)
    fts = has_fts5(con)

    cur = con.execute("DELETE FROM observations WHERE created_at < ?", (cutoff_str,))
    deleted = cur.rowcount
    con.commit()

    if fts and deleted > 0:
        try:
            con.execute("INSERT INTO observations_fts(observations_fts) VALUES ('rebuild')")
            con.commit()
        except Exception:
            pass

    con.close()
    print(f"pruned {deleted} observations")


def main():
    parser = argparse.ArgumentParser(prog="db.py")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init")

    p = sub.add_parser("session-start")
    p.add_argument("session_id")
    p.add_argument("project")

    p = sub.add_parser("session-end")
    p.add_argument("session_id")
    p.add_argument("content")
    p.add_argument("tags", nargs="?", default="")

    p = sub.add_parser("observe")
    p.add_argument("session_id")
    p.add_argument("project")
    p.add_argument("content")
    p.add_argument("tags", nargs="?", default="")

    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--project", default=None)
    p.add_argument("--limit", type=int, default=2)

    sub.add_parser("stats")

    p = sub.add_parser("prune")
    p.add_argument("--days", type=int, default=90)

    p = sub.add_parser("forget")
    p.add_argument("query", help="Search term to match observations for deletion")

    args = parser.parse_args()

    dispatch = {
        "init": cmd_init,
        "session-start": cmd_session_start,
        "session-end": cmd_session_end,
        "observe": cmd_observe,
        "search": cmd_search,
        "stats": cmd_stats,
        "prune": cmd_prune,
        "forget": cmd_forget,
    }

    if args.cmd in dispatch:
        dispatch[args.cmd](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

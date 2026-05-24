#!/usr/bin/env python3
"""lstack persistent memory — all DB operations via subcommands."""

import sqlite3
import json
import sys
import os
import re
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

DB_PATH = Path(os.environ.get(
    "LSTACK_DB_PATH",
    str(Path.home() / ".claude" / "memory" / "lstack.db")
))
CONFIG_PATH = Path(os.environ.get(
    "LSTACK_CONFIG_PATH",
    str(DB_PATH.parent / "lstack-config.json")
))
LEGACY_CONFIG_PATH = DB_PATH.parent / "config.json"

LEARNING_TYPES = {
    "pattern",
    "pitfall",
    "preference",
    "architecture",
    "tool",
    "operational",
    "investigation",
}

LEARNING_SOURCES = {
    "observed",
    "user-stated",
    "inferred",
    "cross-model",
}

LEARNING_DEFAULT_CONFIDENCE = {
    "user-stated": 10,
    "observed": 8,
    "cross-model": 8,
    "inferred": 5,
}

LEARNING_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,119}$")
PROMPT_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions|ignore\s+all\s+previous|you\s+are\s+now|"
    r"always\s+output\s+no\s+findings|skip\s+security|skip\s+all\s+checks|"
    r"do\s+not\s+report|approve\s+all|"
    r"(^|\n)\s*(system|assistant|user|override)\s*:)",
    re.IGNORECASE,
)

CONFIG_DEFAULTS = {
    "cross_project_learnings": False,
    "learning_auto_extract": True,
    "learning_extract_llm": False,
    "learning_extract_markers": True,
    "learning_max_markers": 5,
    "learning_stop_no_embed": True,
    "learning_decay_enabled": True,
    "learning_injection_limit": 5,
    "learning_min_effective_confidence": 3,
    "learning_trust_cross_project_only_user_stated": True,
}

STOPWORDS = {
    "from", "import", "return", "const", "function", "class", "interface",
    "export", "default", "null", "true", "false", "this", "with", "then",
    "else", "when", "that", "have", "will", "your", "into", "been", "were",
    "them", "some", "what", "more", "also", "than", "just", "each", "make",
    "type", "void", "async", "await", "string", "number", "boolean",
}

_embed_model = None
_LSTACK_VENV = Path.home() / ".claude" / "venv"

# Add venv to sys.path at import time so sqlite_vec is always importable
def _add_venv_to_path():
    """Add lstack venv site-packages to sys.path if not already there."""
    venv_python = _LSTACK_VENV / "bin" / "python"
    if not venv_python.exists():
        return False
    import subprocess
    try:
        sp = subprocess.check_output(
            [str(venv_python), "-c",
             "import sysconfig; print(sysconfig.get_path('purelib'))"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        if sp and sp not in sys.path:
            sys.path.insert(0, sp)
        return True
    except Exception:
        return False

_add_venv_to_path()


def ensure_deps():
    """Ensure sqlite-vec and sentence-transformers are available.

    Uses the dedicated lstack venv at ~/.claude/venv. Creates it with
    uv if missing.
    """
    missing = []
    try:
        import sqlite_vec
    except ImportError:
        missing.append("sqlite-vec")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        missing.append("sentence-transformers")

    if not missing:
        return

    import subprocess
    venv_python = _LSTACK_VENV / "bin" / "python"

    # Create venv if it doesn't exist
    if not _LSTACK_VENV.exists():
        subprocess.run(
            ["uv", "venv", str(_LSTACK_VENV)],
            capture_output=True, check=False
        )

    # Install into venv via uv pip
    if _LSTACK_VENV.exists():
        subprocess.run(
            ["uv", "pip", "install", "--quiet",
             f"--python={_LSTACK_VENV}", "--"] + missing,
            check=False
        )
        _add_venv_to_path()
    else:
        # Fallback: try system pip with --break-system-packages
        subprocess.run(
            [sys.executable, "-m", "pip", "install",
             "--quiet", "--break-system-packages"] + missing,
            check=False
        )


def embed(text: str) -> bytes:
    """Return 384-dim float32 embedding as bytes. Lazy loads model."""
    global _embed_model
    ensure_deps()
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2"
        )
    import numpy as np
    vec = _embed_model.encode([text], normalize_embeddings=True)[0]
    return np.array(vec, dtype=np.float32).tobytes()


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


def parse_iso(value):
    if not value:
        return datetime.now(timezone.utc)
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def load_config():
    cfg = dict(CONFIG_DEFAULTS)
    for path in (LEGACY_CONFIG_PATH, CONFIG_PATH):
        try:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    cfg.update({k: raw[k] for k in CONFIG_DEFAULTS if k in raw})
        except Exception:
            pass
    return cfg


def save_config(updates):
    cfg = load_config()
    cfg.update({k: v for k, v in updates.items() if k in CONFIG_DEFAULTS})
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, sort_keys=True)
        f.write("\n")
    return cfg


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


def slugify_key(text):
    tokens = extract_keywords(text)
    if tokens:
        slug = "-".join(tokens[:5])
    else:
        slug = re.sub(r"[^a-z0-9_.-]+", "-", text.lower()).strip("-._")
    slug = re.sub(r"[^a-z0-9_.-]+", "-", slug.lower()).strip("-._")
    return slug[:80] or "learning"


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


def get_git_branch(cwd=None):
    try:
        import subprocess
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            cwd=cwd or os.getcwd(), stderr=subprocess.DEVNULL
        ).decode().strip()
        return branch or None
    except Exception:
        return None


def get_git_commit(cwd=None):
    try:
        import subprocess
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd or os.getcwd(), stderr=subprocess.DEVNULL
        ).decode().strip()
        return sha or None
    except Exception:
        return None


def normalize_learning_file(path, project=None):
    if not path:
        return None
    raw = os.path.expanduser(str(path))
    project = normalize_project(project or get_project())
    if project == "global":
        return raw.replace("\\", "/")
    try:
        abs_path = os.path.realpath(raw)
        if not os.path.isabs(raw):
            abs_path = os.path.realpath(os.path.join(os.getcwd(), raw))
        proj_native = project
        m = re.match(r"^([A-Z]):/(.*)", project)
        if m and os.name != "nt":
            proj_native = f"/{m.group(1).lower()}/{m.group(2)}"
        rel = os.path.relpath(abs_path, os.path.realpath(proj_native))
        if not rel.startswith("..") and not os.path.isabs(rel):
            return rel.replace("\\", "/")
    except Exception:
        pass
    return raw.replace("\\", "/")


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


def ensure_learning_columns(con):
    required = {
        "session_id": "TEXT NOT NULL DEFAULT ''",
        "project": "TEXT NOT NULL DEFAULT ''",
        "key": "TEXT NOT NULL DEFAULT ''",
        "type": "TEXT NOT NULL DEFAULT ''",
        "insight": "TEXT NOT NULL DEFAULT ''",
        "confidence": "INTEGER NOT NULL DEFAULT 5",
        "source": "TEXT NOT NULL DEFAULT 'observed'",
        "trusted": "INTEGER NOT NULL DEFAULT 0",
        "tags": "TEXT",
        "files_json": "TEXT",
        "branch": "TEXT",
        "commit_sha": "TEXT",
        "metadata_json": "TEXT",
        "supersedes_id": "INTEGER",
        "embedding": "BLOB",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    try:
        existing = {
            row[1] for row in con.execute("PRAGMA table_info(learnings)").fetchall()
        }
    except Exception:
        return
    for column, ddl in required.items():
        if column not in existing:
            try:
                con.execute(f"ALTER TABLE learnings ADD COLUMN {column} {ddl}")
            except Exception:
                pass


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

        CREATE TABLE IF NOT EXISTS learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            project TEXT NOT NULL,
            key TEXT NOT NULL,
            type TEXT NOT NULL,
            insight TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            source TEXT NOT NULL,
            trusted INTEGER NOT NULL DEFAULT 0,
            tags TEXT,
            files_json TEXT,
            branch TEXT,
            commit_sha TEXT,
            metadata_json TEXT,
            supersedes_id INTEGER,
            embedding BLOB,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_learnings_project_type_key_created
            ON learnings(project, type, key, created_at);
        CREATE INDEX IF NOT EXISTS idx_learnings_project_created
            ON learnings(project, created_at);
        CREATE INDEX IF NOT EXISTS idx_learnings_type
            ON learnings(type);
        CREATE INDEX IF NOT EXISTS idx_learnings_source
            ON learnings(source);
        CREATE INDEX IF NOT EXISTS idx_learnings_trusted
            ON learnings(trusted);
        CREATE INDEX IF NOT EXISTS idx_learnings_key
            ON learnings(key);
    """)

    ensure_learning_columns(con)

    # Add embedding column if not present
    try:
        con.execute("ALTER TABLE observations ADD COLUMN embedding BLOB")
        con.commit()
    except Exception:
        pass  # column already exists

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

            CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(
                key,
                type,
                insight,
                tags,
                content=learnings,
                content_rowid=id
            );

            CREATE TRIGGER IF NOT EXISTS learning_ai AFTER INSERT ON learnings BEGIN
                INSERT INTO learnings_fts(rowid, key, type, insight, tags)
                VALUES (new.id, new.key, new.type, new.insight, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS learning_ad AFTER DELETE ON learnings BEGIN
                INSERT INTO learnings_fts(learnings_fts, rowid, key, type, insight, tags)
                VALUES ('delete', old.id, old.key, old.type, old.insight, old.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS learning_au AFTER UPDATE ON learnings BEGIN
                INSERT INTO learnings_fts(learnings_fts, rowid, key, type, insight, tags)
                VALUES ('delete', old.id, old.key, old.type, old.insight, old.tags);
                INSERT INTO learnings_fts(rowid, key, type, insight, tags)
                VALUES (new.id, new.key, new.type, new.insight, new.tags);
            END;
        """)

    # Add sqlite-vec virtual table
    try:
        import sqlite_vec
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        con.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS observations_vec
            USING vec0(embedding float[384])
        """)
        con.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS learnings_vec
            USING vec0(embedding float[384])
        """)
        con.commit()
    except Exception:
        pass  # sqlite-vec not available, fall back to FTS5

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


def has_learnings_fts(con):
    try:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='learnings_fts'"
        ).fetchone()
        return row is not None
    except Exception:
        return False


def has_learnings_vec(con):
    try:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='learnings_vec'"
        ).fetchone()
        return row is not None
    except Exception:
        return False


def try_load_sqlite_vec(con):
    try:
        import sqlite_vec
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        return True
    except Exception:
        try:
            con.enable_load_extension(False)
        except Exception:
            pass
        return False


def clamp_learning_tags(tags):
    if tags is None:
        return ""
    if isinstance(tags, str):
        raw = re.split(r"[, \n\t]+", tags)
    else:
        raw = []
        for t in tags:
            raw.extend(re.split(r"[, \n\t]+", str(t)))
    cleaned = []
    seen = set()
    for tag in raw:
        tag = tag.strip().lower()
        tag = re.sub(r"[^a-z0-9_.-]+", "-", tag).strip("-._")[:20]
        if tag and tag not in seen:
            seen.add(tag)
            cleaned.append(tag)
        if len(cleaned) >= 10:
            break
    return ",".join(cleaned)


def validate_learning_input(
    key,
    learning_type,
    insight,
    confidence=None,
    source="observed",
    trusted=None,
    trusted_requested=False,
    tags=None,
):
    source = (source or "observed").strip()
    learning_type = (learning_type or "").strip()
    if learning_type not in LEARNING_TYPES:
        raise ValueError(f"invalid learning type: {learning_type}")
    if source not in LEARNING_SOURCES:
        raise ValueError(f"invalid learning source: {source}")

    key = (key or "").strip().lower()
    if not LEARNING_KEY_RE.match(key):
        raise ValueError(
            "invalid learning key: use lowercase letters, numbers, hyphen, underscore, dot"
        )

    insight = re.sub(r"\s+", " ", (insight or "").strip())
    if not insight:
        raise ValueError("insight is required")
    if PROMPT_INJECTION_RE.search(insight):
        raise ValueError("unsafe instruction-like insight rejected")
    insight = insight[:1000]

    if confidence is None:
        confidence = LEARNING_DEFAULT_CONFIDENCE[source]
    try:
        confidence = int(confidence)
    except Exception as exc:
        raise ValueError("confidence must be an integer from 1 to 10") from exc
    if confidence < 1 or confidence > 10:
        raise ValueError("confidence must be between 1 and 10")

    if trusted is None:
        trusted = source == "user-stated" or bool(trusted_requested)
    trusted = bool(trusted)
    if trusted and source != "user-stated" and not trusted_requested:
        raise ValueError("trusted non-user-stated learnings require explicit confirmation")

    return {
        "key": key,
        "type": learning_type,
        "insight": insight,
        "confidence": confidence,
        "source": source,
        "trusted": 1 if trusted else 0,
        "tags": clamp_learning_tags(tags),
    }


def effective_confidence(row, decay_enabled=True, now=None):
    confidence = int(row.get("confidence", 0) or 0)
    if confidence <= 0 or not decay_enabled:
        return max(0, confidence)

    source = row.get("source") or ""
    trusted = bool(row.get("trusted"))
    if source == "user-stated" and trusted:
        return confidence
    if source == "cross-model" and trusted:
        return confidence

    if source in {"observed", "inferred"}:
        window = 30
    elif source == "cross-model":
        window = 60
    else:
        return confidence

    created = parse_iso(row.get("created_at"))
    now = now or datetime.now(timezone.utc)
    days = max(0, int((now - created).total_seconds() // 86400))
    return max(0, confidence - (days // window))


def learning_row_to_dict(row, decay_enabled=True, score=None, method=None):
    columns = [
        "id", "session_id", "project", "key", "type", "insight",
        "confidence", "source", "trusted", "tags", "files_json", "branch",
        "commit_sha", "metadata_json", "supersedes_id", "created_at",
        "updated_at",
    ]
    item = dict(zip(columns, row[:len(columns)]))
    item["trusted"] = bool(item["trusted"])
    item["effective_confidence"] = effective_confidence(item, decay_enabled)
    try:
        item["files"] = json.loads(item.get("files_json") or "[]")
    except Exception:
        item["files"] = []
    try:
        item["metadata"] = json.loads(item.get("metadata_json") or "{}")
    except Exception:
        item["metadata"] = {}
    if score is not None:
        item["score"] = score
    if method is not None:
        item["method"] = method
    return item


LEARNING_COLUMNS = (
    "learnings.id, learnings.session_id, learnings.project, learnings.key, "
    "learnings.type, learnings.insight, learnings.confidence, "
    "learnings.source, learnings.trusted, learnings.tags, "
    "learnings.files_json, learnings.branch, learnings.commit_sha, "
    "learnings.metadata_json, learnings.supersedes_id, "
    "learnings.created_at, learnings.updated_at"
)
LEARNING_SELECT = f"SELECT {LEARNING_COLUMNS} FROM learnings"


def maybe_embed_learning(con, learning_id, text):
    if embeddings_disabled():
        return False
    if not has_learnings_vec(con) or not try_load_sqlite_vec(con):
        return False
    try:
        vec = embed(text)
        con.execute("UPDATE learnings SET embedding = ? WHERE id = ?", (vec, learning_id))
        con.execute(
            "INSERT OR REPLACE INTO learnings_vec(rowid, embedding) VALUES (?, ?)",
            (learning_id, vec)
        )
        con.commit()
        return True
    except Exception:
        return False


def insert_learning(
    con,
    session_id,
    project,
    key,
    learning_type,
    insight,
    confidence=None,
    source="observed",
    trusted=None,
    trusted_requested=False,
    tags=None,
    files=None,
    branch=None,
    commit_sha=None,
    metadata=None,
    created_at=None,
    updated_at=None,
    embed_on_write=True,
):
    init_db(con)
    fields = validate_learning_input(
        key, learning_type, insight, confidence, source,
        trusted, trusted_requested, tags
    )
    project = normalize_project(project or get_project())
    now = iso_now()
    created_at = created_at or now
    updated_at = updated_at or created_at
    files = files or []
    files = [normalize_learning_file(f, project) for f in files if f][:20]
    metadata = metadata or {}

    cur = con.execute(
        "INSERT INTO learnings (session_id, project, key, type, insight, "
        "confidence, source, trusted, tags, files_json, branch, commit_sha, "
        "metadata_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id or "manual",
            project,
            fields["key"],
            fields["type"],
            fields["insight"],
            fields["confidence"],
            fields["source"],
            fields["trusted"],
            fields["tags"],
            json.dumps(files),
            branch,
            commit_sha,
            json.dumps(metadata, sort_keys=True),
            created_at,
            updated_at,
        )
    )
    new_id = cur.lastrowid

    older = con.execute(
        "SELECT id FROM learnings WHERE project = ? AND type = ? AND key = ? "
        "AND id != ? AND supersedes_id IS NULL ORDER BY created_at DESC, id DESC",
        (project, fields["type"], fields["key"], new_id)
    ).fetchall()
    for (old_id,) in older:
        con.execute(
            "UPDATE learnings SET supersedes_id = ?, updated_at = ? WHERE id = ?",
            (new_id, now, old_id)
        )

    con.commit()
    if embed_on_write:
        maybe_embed_learning(
            con,
            new_id,
            f"{fields['key']} {fields['type']} {fields['insight']} {fields['tags']}"
        )
    return new_id


def embeddings_disabled():
    return (
        os.environ.get("LSTACK_SKIP_EMBEDDINGS") == "1"
        or os.environ.get("LSTACK_NO_EMBED") == "1"
    )


def learning_scope_sql(project=None, global_only=False, cross_project=False,
                       trusted_only=False):
    where = []
    params = []
    project = normalize_project(project or get_project())
    if global_only:
        where.append("learnings.project = 'global'")
    elif cross_project:
        where.append("learnings.project != ?")
        params.append(project)
        where.append("learnings.trusted = 1")
    else:
        where.append(
            "(learnings.project = ? OR "
            "(learnings.project = 'global' AND learnings.trusted = 1))"
        )
        params.append(project)

    if trusted_only:
        where.append("learnings.trusted = 1")
    return where, params


def learning_type_sql(learning_type):
    if not learning_type:
        return [], []
    if learning_type not in LEARNING_TYPES:
        raise ValueError(f"invalid learning type: {learning_type}")
    return ["learnings.type = ?"], [learning_type]


def fts_query(query):
    kws = extract_keywords(query)
    if not kws:
        return None
    return " OR ".join(kws)


def dedupe_learnings(items, cross_project=False, include_superseded=False):
    if include_superseded:
        return items
    winners = {}
    for item in items:
        if item.get("supersedes_id"):
            continue
        key = (item["type"], item["key"]) if cross_project else (
            item["project"], item["type"], item["key"]
        )
        existing = winners.get(key)
        if not existing or (
            (item.get("updated_at") or item.get("created_at") or "", item["id"]) >
            (existing.get("updated_at") or existing.get("created_at") or "", existing["id"])
        ):
            winners[key] = item
    return list(winners.values())


def sort_learnings(items):
    def ts(item):
        return parse_iso(item.get("updated_at") or item.get("created_at")).timestamp()
    return sorted(
        items,
        key=lambda it: (
            -int(it.get("effective_confidence", 0)),
            -(float(it.get("score", 0)) if it.get("score") is not None else 0.0),
            -ts(it),
            -int(it.get("id", 0)),
        )
    )


def search_learnings(
    con,
    query,
    project=None,
    global_only=False,
    cross_project=False,
    trusted_only=False,
    learning_type=None,
    limit=10,
    decay_enabled=True,
    include_superseded=False,
    min_effective_confidence=None,
):
    init_db(con)
    limit = max(1, min(int(limit or 10), 100))
    where, params = learning_scope_sql(project, global_only, cross_project, trusted_only)
    type_where, type_params = learning_type_sql(learning_type)
    where += type_where
    params += type_params
    if not include_superseded:
        where.append("learnings.supersedes_id IS NULL")
    where_sql = " AND ".join(where) if where else "1=1"
    items = []
    method = "like"

    if query:
        try:
            if has_learnings_vec(con) and try_load_sqlite_vec(con):
                query_vec = embed(query)
                rows = con.execute(
                    f"SELECT {LEARNING_COLUMNS}, v.distance FROM learnings_vec v "
                    f"JOIN learnings ON learnings.id = v.rowid "
                    f"WHERE {where_sql} AND v.embedding MATCH ? AND k = ? "
                    "ORDER BY v.distance",
                    params + [query_vec, limit * 5]
                ).fetchall()
                items = [
                    learning_row_to_dict(row[:-1], decay_enabled,
                                         round(1 - float(row[-1]), 3), "semantic")
                    for row in rows
                ]
                method = "semantic"
        except Exception:
            items = []

    if not items and query and has_learnings_fts(con):
        q = fts_query(query)
        if q:
            try:
                rows = con.execute(
                    f"SELECT {LEARNING_COLUMNS} FROM learnings_fts f "
                    f"JOIN learnings ON learnings.id = f.rowid "
                    f"WHERE learnings_fts MATCH ? AND {where_sql} "
                    "ORDER BY rank LIMIT ?",
                    [q] + params + [limit * 5]
                ).fetchall()
                items = [
                    learning_row_to_dict(row, decay_enabled, None, "fts")
                    for row in rows
                ]
                method = "fts"
            except Exception:
                items = []

    if not items:
        if query:
            like = f"%{query}%"
            qwhere = (
                "(key LIKE ? OR type LIKE ? OR insight LIKE ? OR tags LIKE ?)"
            )
            rows = con.execute(
                f"{LEARNING_SELECT} WHERE {where_sql} AND {qwhere} "
                "ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                params + [like, like, like, like, limit * 5]
            ).fetchall()
        else:
            rows = con.execute(
                f"{LEARNING_SELECT} WHERE {where_sql} "
                "ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                params + [limit * 5]
            ).fetchall()
        items = [learning_row_to_dict(row, decay_enabled, None, method) for row in rows]

    items = dedupe_learnings(items, cross_project, include_superseded)
    if min_effective_confidence is not None:
        items = [
            item for item in items
            if int(item.get("effective_confidence", 0)) >= int(min_effective_confidence)
        ]
    return sort_learnings(items)[:limit]


def list_learnings(con, project=None, global_only=False, learning_type=None,
                   trusted_only=False, limit=50, decay_enabled=True):
    return search_learnings(
        con, "", project=project, global_only=global_only,
        trusted_only=trusted_only, learning_type=learning_type,
        limit=limit, decay_enabled=decay_enabled,
    )


def learning_context(con, project=None, limit=None, include_cross_project=False):
    cfg = load_config()
    limit = int(limit or cfg.get("learning_injection_limit", 5))
    project = normalize_project(project or get_project())
    min_conf = int(cfg.get("learning_min_effective_confidence", 3))

    project_items = search_learnings(
        con, "", project=project, limit=limit, min_effective_confidence=min_conf
    )
    global_items = search_learnings(
        con, "", project=project, global_only=True, trusted_only=True,
        limit=limit, min_effective_confidence=min_conf
    )
    global_items = [item for item in global_items if item.get("source") == "user-stated"]
    items = project_items + global_items

    if include_cross_project and cfg.get("cross_project_learnings", False):
        cross = search_learnings(
            con, "", project=project, cross_project=True, trusted_only=True,
            limit=limit, min_effective_confidence=min_conf
        )
        if cfg.get("learning_trust_cross_project_only_user_stated", True):
            cross = [item for item in cross if item.get("source") == "user-stated"]
        items.extend(cross)

    items = dedupe_learnings(items, include_superseded=False)
    items = sort_learnings(items)[:limit]
    lines = []
    for item in items:
        date = (item.get("created_at") or "")[:10]
        conf = item.get("effective_confidence", item.get("confidence"))
        lines.append(
            f"[{item['type']}/{item['key']}] confidence {conf}/10 "
            f"{item['source']} {date}\n{item['insight']}"
        )
    if not lines:
        return ""
    return "--- structured learnings ---\n" + "\n".join(lines) + "\n--- end structured learnings ---"


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
    cur = con.execute(
        "INSERT INTO observations (session_id, project, content, tags, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, project, content, tags[:200], iso_now())
    )
    con.commit()
    row_id = cur.lastrowid

    if not embeddings_disabled():
        try:
            import sqlite_vec
            vec = embed(content)
            con.enable_load_extension(True)
            sqlite_vec.load(con)
            con.enable_load_extension(False)
            con.execute(
                "INSERT INTO observations_vec(rowid, embedding) VALUES (?, ?)",
                (row_id, vec)
            )
            con.commit()
        except Exception:
            pass

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

    if not args.no_embed and not embeddings_disabled():
        try:
            import sqlite_vec
            vec = embed(content)
            con.enable_load_extension(True)
            sqlite_vec.load(con)
            con.enable_load_extension(False)
            con.execute(
                "INSERT INTO observations_vec(rowid, embedding) VALUES (?, ?)",
                (row_id, vec)
            )
            con.commit()
        except Exception:
            pass

    con.close()
    print(f"ok {row_id}")


def cmd_search(args):
    query = args.query
    project = normalize_project(os.path.realpath(args.project)) if args.project else None
    limit = min(args.limit or 5, 10)

    con = connect()
    init_db(con)

    # Try semantic search first
    try:
        ensure_deps()
        import sqlite_vec
        query_vec = embed(query)

        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)

        if project:
            rows = con.execute("""
                SELECT o.id, o.content, o.project, o.created_at, o.tags,
                       v.distance
                FROM observations_vec v
                JOIN observations o ON o.id = v.rowid
                WHERE (o.project = ? OR o.project = 'global')
                AND v.embedding MATCH ?
                AND k = ?
                ORDER BY v.distance
            """, (project, query_vec, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT o.id, o.content, o.project, o.created_at, o.tags,
                       v.distance
                FROM observations_vec v
                JOIN observations o ON o.id = v.rowid
                WHERE v.embedding MATCH ?
                AND k = ?
                ORDER BY v.distance
            """, (query_vec, limit)).fetchall()

        results = []
        for row_id, content, proj, created_at, tags, distance in rows:
            results.append({
                "id": row_id,
                "content": content,
                "project": proj,
                "created_at": created_at,
                "tags": tags or "",
                "score": round(1 - float(distance), 3),
                "method": "semantic"
            })
        con.close()
        print(json.dumps(results))
        return

    except Exception:
        pass  # fall through to FTS5

    fts = has_fts5(con)
    results = []
    try:
        if fts:
            if project:
                rows = con.execute(
                    """SELECT o.id, o.content, o.project, o.created_at, o.tags
                       FROM observations_fts f
                       JOIN observations o ON o.id = f.rowid
                       WHERE observations_fts MATCH ?
                       AND (o.project = ? OR o.project = 'global')
                       ORDER BY rank LIMIT ?""",
                    (query, project, limit)
                ).fetchall()
            else:
                rows = con.execute(
                    """SELECT o.id, o.content, o.project, o.created_at, o.tags
                       FROM observations_fts f
                       JOIN observations o ON o.id = f.rowid
                       WHERE observations_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (query, limit)
                ).fetchall()
        else:
            print("FTS5 unavailable, using LIKE search (slower)", file=sys.stderr)
            keywords = query.replace(",", " ").split()
            if keywords:
                kw = keywords[0]
                like = f"%{kw}%"
                if project:
                    rows = con.execute(
                        "SELECT id, content, project, created_at, tags FROM observations "
                        "WHERE (content LIKE ? OR tags LIKE ?) "
                        "AND (project = ? OR project = 'global') "
                        "ORDER BY created_at DESC LIMIT ?",
                        (like, like, project, limit)
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT id, content, project, created_at, tags FROM observations "
                        "WHERE content LIKE ? OR tags LIKE ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (like, like, limit)
                    ).fetchall()
            else:
                rows = []

        for row_id, content, proj, created_at, tags in rows:
            results.append({
                "id": row_id,
                "content": content,
                "project": proj,
                "created_at": created_at,
                "tags": tags or "",
            })
    except Exception:
        results = []

    con.close()
    print(json.dumps(results))


def cmd_embed_all(args):
    """Backfill embeddings for all observations missing vectors."""
    if embeddings_disabled():
        print("embeddings skipped by environment")
        return
    ensure_deps()
    con = connect()
    init_db(con)

    try:
        import sqlite_vec
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
    except Exception:
        print("sqlite-vec not available")
        con.close()
        return

    # Find observations with no vector
    existing = set(
        r[0] for r in con.execute(
            "SELECT rowid FROM observations_vec"
        ).fetchall()
    )
    all_obs = con.execute(
        "SELECT id, content FROM observations"
    ).fetchall()
    missing = [(id_, content) for id_, content in all_obs
               if id_ not in existing]

    print(f"Backfilling {len(missing)} observations...")
    for i, (obs_id, content) in enumerate(missing):
        vec = embed(content)
        con.execute(
            "INSERT OR IGNORE INTO observations_vec(rowid, embedding) "
            "VALUES (?, ?)",
            (obs_id, vec)
        )
        if i % 10 == 0:
            con.commit()
            print(f"  {i}/{len(missing)}")
    con.commit()
    print(f"Done. Backfilled {len(missing)} observations.")
    con.close()


def cmd_edit(args):
    con = connect()
    init_db(con)
    fts = has_fts5(con)

    row = con.execute(
        "SELECT id, content, tags, project FROM observations WHERE id = ?",
        (args.id,)
    ).fetchone()

    if not row:
        print(json.dumps({"error": f"No observation with id {args.id}"}))
        con.close()
        return

    obs_id, content, tags, project = row

    new_content = args.content if args.content is not None else content
    new_tags = args.tags if args.tags is not None else tags
    new_project = args.project if args.project is not None else project

    if new_project and new_project != "global":
        new_project = normalize_project(new_project)

    con.execute(
        "UPDATE observations SET content = ?, tags = ?, project = ? WHERE id = ?",
        (new_content, new_tags, new_project, obs_id)
    )
    con.commit()

    if fts:
        try:
            con.execute("INSERT INTO observations_fts(observations_fts) VALUES ('rebuild')")
            con.commit()
        except Exception:
            pass

    con.close()
    print(json.dumps({
        "edited": obs_id,
        "content": new_content,
        "tags": new_tags,
        "project": new_project,
    }))


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


def cmd_analytics(args):
    """Show session and memory analytics."""
    import sys as _sys
    if hasattr(_sys.stdout, 'reconfigure'):
        try:
            _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    project = normalize_project(get_project())
    con = connect()
    init_db(con)

    import time

    # Observations per week (last 4 weeks)
    weeks = []
    for i in range(4):
        week_start = time.time() - (i + 1) * 7 * 86400
        week_end = time.time() - i * 7 * 86400
        start_str = datetime.fromtimestamp(week_start, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = datetime.fromtimestamp(week_end, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        count = con.execute(
            "SELECT COUNT(*) FROM observations WHERE created_at >= ? AND created_at < ?",
            (start_str, end_str)
        ).fetchone()[0]
        weeks.append((f"week-{i}", count))

    # Global vs project ratio
    global_count = con.execute(
        "SELECT COUNT(*) FROM observations WHERE project = 'global'"
    ).fetchone()[0]
    proj_count = con.execute(
        "SELECT COUNT(*) FROM observations WHERE project = ?",
        (project,)
    ).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    # Top tags
    tags_raw = con.execute(
        "SELECT tags FROM observations WHERE tags != '' ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    tag_counts = {}
    for (tags,) in tags_raw:
        for tag in tags.split(","):
            tag = tag.strip()
            if tag:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:10]

    # Sessions this week
    week_ago = datetime.fromtimestamp(
        time.time() - 7 * 86400, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    sessions_week = con.execute(
        "SELECT COUNT(*) FROM sessions WHERE started_at >= ?",
        (week_ago,)
    ).fetchone()[0]

    learning_total = con.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
    learning_by_type = con.execute(
        "SELECT type, COUNT(*) FROM learnings GROUP BY type ORDER BY type"
    ).fetchall()
    learning_by_source = con.execute(
        "SELECT source, COUNT(*) FROM learnings GROUP BY source ORDER BY source"
    ).fetchall()
    learning_trusted = con.execute(
        "SELECT COUNT(*) FROM learnings WHERE trusted = 1"
    ).fetchone()[0]
    learning_superseded = con.execute(
        "SELECT COUNT(*) FROM learnings WHERE supersedes_id IS NOT NULL"
    ).fetchone()[0]
    learning_projects = con.execute(
        "SELECT project, COUNT(*) FROM learnings "
        "GROUP BY project ORDER BY COUNT(*) DESC, project LIMIT 5"
    ).fetchall()
    learning_keys = con.execute(
        "SELECT key, COUNT(*) FROM learnings "
        "GROUP BY key HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC, key LIMIT 5"
    ).fetchall()
    learning_rows = con.execute(f"{LEARNING_SELECT}").fetchall()

    con.close()

    threshold = int(load_config().get("learning_min_effective_confidence", 3))
    learning_decayed = sum(
        1 for row in learning_rows
        if learning_row_to_dict(row).get("effective_confidence", 0) < threshold
    )

    print(f"=== lstack analytics ===")
    print(f"")
    print(f"Sessions this week:     {sessions_week}")
    print(f"Total observations:     {total}")
    print(f"  This project:         {proj_count}")
    print(f"  Global:               {global_count}")
    print(f"")
    print(f"Observations per week (newest first):")
    for label, count in weeks:
        bar = '#' * count + '-' * max(0, 10 - count)
        print(f"  {label}:  {bar[:10]} {count}")
    print(f"")
    if top_tags:
        print(f"Top tags:")
        for tag, count in top_tags:
            print(f"  {tag:<20} {count}")
    else:
        print(f"Top tags: (none yet)")
    print(f"")
    print(f"Structured learnings:")
    print(f"  Total:                {learning_total}")
    print(f"  Trusted:              {learning_trusted}")
    print(f"  Untrusted:            {learning_total - learning_trusted}")
    print(f"  Decayed below useful: {learning_decayed}")
    print(f"  Superseded:           {learning_superseded}")
    if learning_by_type:
        print(f"  By type:")
        for name, count in learning_by_type:
            print(f"    {name:<14} {count}")
    if learning_by_source:
        print(f"  By source:")
        for name, count in learning_by_source:
            print(f"    {name:<14} {count}")
    if learning_keys:
        print(f"  Repeated keys:")
        for key, count in learning_keys:
            print(f"    {key:<24} {count}")
    if learning_projects:
        print(f"  Top project scopes:")
        for scope, count in learning_projects:
            label = "global" if scope == "global" else scope
            print(f"    {label[:40]:<40} {count}")


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


def cmd_export(args):
    """Export all observations to JSON for sync."""
    con = connect()
    init_db(con)
    rows = con.execute(
        "SELECT id, session_id, project, content, tags, created_at "
        "FROM observations ORDER BY created_at ASC"
    ).fetchall()
    con.close()
    observations = [
        {
            "id": r[0], "session_id": r[1], "project": r[2],
            "content": r[3], "tags": r[4], "created_at": r[5]
        }
        for r in rows
    ]
    output = {"version": 2, "exported_at": iso_now(),
              "observations": observations}
    print(json.dumps(output, indent=2))


def cmd_import(args):
    """Import observations from JSON, skipping duplicates by content+project."""
    path = args.file
    with open(path) as f:
        data = json.load(f)
    observations = data.get("observations", [])
    con = connect()
    init_db(con)
    imported = 0
    skipped = 0
    for obs in observations:
        exists = con.execute(
            "SELECT 1 FROM observations WHERE content = ? AND project = ?",
            (obs["content"], obs["project"])
        ).fetchone()
        if exists:
            skipped += 1
            continue
        con.execute(
            "INSERT INTO observations (session_id, project, content, tags, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (obs.get("session_id", "sync"), obs["project"],
             obs["content"], obs.get("tags", ""), obs["created_at"])
        )
        imported += 1
    con.commit()
    con.close()
    print(f"Imported {imported} observations, skipped {skipped} duplicates.")


def format_learning_text(items):
    if not items:
        return "No learnings found."
    grouped = {}
    for item in items:
        grouped.setdefault(item["type"], []).append(item)
    lines = []
    for learning_type in sorted(grouped):
        lines.append(f"{learning_type}:")
        for item in grouped[learning_type]:
            scope = "global" if item["project"] == "global" else item["project"]
            date = (item.get("created_at") or "")[:10]
            files = ", ".join(item.get("files") or [])
            conf = item.get("confidence")
            eff = item.get("effective_confidence")
            suffix = f" files: {files}" if files else ""
            lines.append(
                f"  {item['id']:>4}  {date}  {item['key']}  "
                f"{item['source']} trusted={str(item['trusted']).lower()} "
                f"confidence={conf}/{eff}  [{scope}]"
            )
            lines.append(f"        {item['insight'][:1000]}{suffix}")
    return "\n".join(lines)


def print_learning_results(items, as_json=False):
    if as_json:
        print(json.dumps(items, indent=2))
    else:
        print(format_learning_text(items))


def cmd_learn_add(args):
    project = "global" if args.global_scope else (
        normalize_project(os.path.realpath(args.project)) if args.project else
        normalize_project(get_project())
    )
    files = args.file or []
    metadata = {}
    if args.metadata_json:
        try:
            metadata = json.loads(args.metadata_json)
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be a JSON object")
        except Exception as exc:
            print(json.dumps({"error": f"invalid metadata_json: {exc}"}), file=sys.stderr)
            sys.exit(2)

    con = connect()
    try:
        row_id = insert_learning(
            con,
            session_id=args.session_id or "manual",
            project=project,
            key=args.key,
            learning_type=args.type,
            insight=args.insight,
            confidence=args.confidence,
            source=args.source,
            trusted=args.trusted if args.trusted else None,
            trusted_requested=args.trusted,
            tags=args.tag or "",
            files=files,
            branch=args.branch if args.branch is not None else (
                None if project == "global" else get_git_branch(project)
            ),
            commit_sha=args.commit_sha if args.commit_sha is not None else (
                None if project == "global" else get_git_commit(project)
            ),
            metadata=metadata,
        )
        row = con.execute(f"{LEARNING_SELECT} WHERE learnings.id = ?", (row_id,)).fetchone()
        item = learning_row_to_dict(row)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        con.close()
        sys.exit(2)
    con.close()
    if args.json:
        print(json.dumps(item, indent=2))
    else:
        print(f"ok {row_id}")


def cmd_learn_search(args):
    query = " ".join(args.query).strip()
    if not query:
        print("Usage: learn-search QUERY", file=sys.stderr)
        sys.exit(2)
    if (
        args.cross_project
        and not args.json
        and sys.stdin.isatty()
        and not load_config().get("cross_project_learnings", False)
    ):
        print(
            "lstack can search trusted user-stated learnings from other projects "
            "on this machine. This stays local. Enable cross-project trusted learnings?"
        )
        print("A) Enable trusted cross-project learnings")
        print("B) Keep learnings project-scoped")
        choice = input("[A/B] ").strip().lower()
        if choice.startswith("a"):
            save_config({"cross_project_learnings": True})
        else:
            args.cross_project = False

    if args.project:
        project = normalize_project(os.path.realpath(args.project))
    elif args.cross_project:
        # Infer current project from cwd so project-local items are always included
        project = normalize_project(get_project())
    else:
        project = None

    decay_enabled = (not args.no_decay) and bool(load_config().get("learning_decay_enabled", True))
    con = connect()
    try:
        if args.cross_project:
            # Pass 1: current project items (any trust level)
            proj_items = search_learnings(
                con, query,
                project=project,
                global_only=False,
                cross_project=False,
                trusted_only=args.trusted_only,
                learning_type=args.type,
                limit=args.limit,
                decay_enabled=decay_enabled,
                include_superseded=args.include_superseded,
            )
            # Pass 2: trusted items from other projects and global
            cross_items = search_learnings(
                con, query,
                project=project,
                global_only=False,
                cross_project=True,
                trusted_only=True,
                learning_type=args.type,
                limit=args.limit,
                decay_enabled=decay_enabled,
                include_superseded=args.include_superseded,
            )
            merged = dedupe_learnings(
                proj_items + cross_items,
                cross_project=True,
                include_superseded=args.include_superseded,
            )
            items = sort_learnings(merged)[: args.limit]
        else:
            items = search_learnings(
                con, query,
                project=project,
                global_only=args.global_scope,
                cross_project=False,
                trusted_only=args.trusted_only,
                learning_type=args.type,
                limit=args.limit,
                decay_enabled=decay_enabled,
                include_superseded=args.include_superseded,
            )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        con.close()
        sys.exit(2)
    con.close()
    if not items and args.cross_project and not args.json:
        print("No cross-project learnings found.")
    else:
        print_learning_results(items, args.json)


def cmd_learn_list(args):
    project = normalize_project(os.path.realpath(args.project)) if args.project else None
    decay_enabled = bool(load_config().get("learning_decay_enabled", True))
    con = connect()
    try:
        items = list_learnings(
            con,
            project=project,
            global_only=args.global_scope,
            learning_type=args.type,
            trusted_only=args.trusted_only,
            limit=args.limit,
            decay_enabled=decay_enabled,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        con.close()
        sys.exit(2)
    con.close()
    print_learning_results(items, args.json)


def cmd_learn_show(args):
    con = connect()
    init_db(con)
    row = con.execute(f"{LEARNING_SELECT} WHERE learnings.id = ?", (args.id,)).fetchone()
    con.close()
    if not row:
        print(json.dumps({"error": f"No learning with id {args.id}"}))
        return
    item = learning_row_to_dict(row)
    if args.json:
        print(json.dumps(item, indent=2))
    else:
        print(format_learning_text([item]))


def matching_learning_ids_for_forget(con, args):
    if args.id is not None:
        return [args.id]
    where = []
    params = []
    if args.key:
        args.key = args.key.lower()
        if not LEARNING_KEY_RE.match(args.key):
            raise ValueError("invalid learning key")
        where.append("learnings.key = ?")
        params.append(args.key)
    if args.type:
        if args.type not in LEARNING_TYPES:
            raise ValueError(f"invalid learning type: {args.type}")
        where.append("learnings.type = ?")
        params.append(args.type)
    if args.project:
        where.append("learnings.project = ?")
        params.append(normalize_project(os.path.realpath(args.project)))
    if args.global_scope:
        where.append("learnings.project = 'global'")
    query = " ".join(args.query or []).strip()
    if query:
        like = f"%{query}%"
        where.append("(learnings.key LIKE ? OR learnings.insight LIKE ? OR learnings.tags LIKE ?)")
        params.extend([like, like, like])
    if not where:
        raise ValueError("provide --id, --key/--type, or a query")
    rows = con.execute(
        f"SELECT learnings.id FROM learnings WHERE {' AND '.join(where)} "
        "ORDER BY learnings.updated_at DESC LIMIT 50",
        params
    ).fetchall()
    return [r[0] for r in rows]


def cmd_learn_forget(args):
    con = connect()
    init_db(con)
    try:
        ids = matching_learning_ids_for_forget(con, args)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        con.close()
        sys.exit(2)
    if not ids:
        con.close()
        print(json.dumps({"deleted": 0, "ids": []}))
        return
    placeholders = ",".join("?" * len(ids))
    rows = con.execute(
        f"{LEARNING_SELECT} WHERE learnings.id IN ({placeholders})",
        ids
    ).fetchall()
    con.execute(f"DELETE FROM learnings WHERE id IN ({placeholders})", ids)
    con.commit()
    if has_learnings_fts(con):
        try:
            con.execute("INSERT INTO learnings_fts(learnings_fts) VALUES ('rebuild')")
            con.commit()
        except Exception:
            pass
    con.close()
    removed = [learning_row_to_dict(row) for row in rows]
    print(json.dumps({"deleted": len(ids), "ids": ids, "removed": removed}, indent=2))


def cmd_learn_promote(args):
    con = connect()
    init_db(con)
    row = con.execute("SELECT id, source FROM learnings WHERE id = ?", (args.id,)).fetchone()
    if not row:
        con.close()
        print(json.dumps({"error": f"No learning with id {args.id}"}))
        return
    con.execute(
        "UPDATE learnings SET trusted = 1, updated_at = ? WHERE id = ?",
        (iso_now(), args.id)
    )
    con.commit()
    con.close()
    print(json.dumps({"promoted": args.id, "trusted": True}))


def cmd_learn_demote(args):
    con = connect()
    init_db(con)
    con.execute(
        "UPDATE learnings SET trusted = 0, updated_at = ? WHERE id = ?",
        (iso_now(), args.id)
    )
    changed = con.total_changes
    con.commit()
    con.close()
    print(json.dumps({"demoted": args.id, "trusted": False, "changed": changed}))


def cmd_learn_stats(args):
    con = connect()
    init_db(con)
    total = con.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
    by_type = dict(con.execute(
        "SELECT type, COUNT(*) FROM learnings GROUP BY type ORDER BY type"
    ).fetchall())
    by_source = dict(con.execute(
        "SELECT source, COUNT(*) FROM learnings GROUP BY source ORDER BY source"
    ).fetchall())
    trusted = con.execute(
        "SELECT COUNT(*) FROM learnings WHERE trusted = 1"
    ).fetchone()[0]
    projects = con.execute(
        "SELECT COUNT(DISTINCT project) FROM learnings"
    ).fetchone()[0]
    superseded = con.execute(
        "SELECT COUNT(*) FROM learnings WHERE supersedes_id IS NOT NULL"
    ).fetchone()[0]
    rows = con.execute(f"{LEARNING_SELECT}").fetchall()
    con.close()
    threshold = int(load_config().get("learning_min_effective_confidence", 3))
    decayed_low = sum(
        1 for row in rows
        if learning_row_to_dict(row).get("effective_confidence", 0) < threshold
    )
    data = {
        "total": total,
        "by_type": by_type,
        "by_source": by_source,
        "trusted": trusted,
        "project_count": projects,
        "decayed_below_useful_threshold": decayed_low,
        "superseded": superseded,
    }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print("=== lstack learning stats ===")
        print(f"Total learnings: {total}")
        print(f"Trusted: {trusted}")
        print(f"Projects: {projects}")
        print(f"Superseded: {superseded}")
        print(f"Decayed below threshold: {decayed_low}")
        print("By type:")
        for k, v in by_type.items():
            print(f"  {k:<14} {v}")
        print("By source:")
        for k, v in by_source.items():
            print(f"  {k:<14} {v}")


def prune_learning_ids(con, args):
    where = []
    params = []
    if args.older_than_days is not None:
        try:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=int(args.older_than_days))
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except OverflowError:
            cutoff = "0001-01-01T00:00:00Z"
        where.append("created_at < ?")
        params.append(cutoff)
    if args.superseded:
        where.append("supersedes_id IS NOT NULL")
    rows = con.execute(
        f"{LEARNING_SELECT} " + (f"WHERE {' AND '.join(where)}" if where else ""),
        params
    ).fetchall()
    items = [learning_row_to_dict(row) for row in rows]
    if args.confidence_below is not None:
        items = [
            item for item in items
            if int(item.get("effective_confidence", 0)) < int(args.confidence_below)
        ]
    return [item["id"] for item in items], items


def cmd_learn_prune(args):
    if not args.dry_run and not args.apply:
        print(json.dumps({"error": "choose --dry-run or --apply"}), file=sys.stderr)
        sys.exit(2)
    if args.older_than_days is None and args.confidence_below is None and not args.superseded:
        print(json.dumps({"error": "provide at least one prune filter"}), file=sys.stderr)
        sys.exit(2)
    con = connect()
    init_db(con)
    ids, items = prune_learning_ids(con, args)
    if args.apply and ids:
        placeholders = ",".join("?" * len(ids))
        con.execute(f"DELETE FROM learnings WHERE id IN ({placeholders})", ids)
        con.commit()
        if has_learnings_fts(con):
            try:
                con.execute("INSERT INTO learnings_fts(learnings_fts) VALUES ('rebuild')")
                con.commit()
            except Exception:
                pass
    con.close()
    print(json.dumps({
        "matched": len(ids),
        "deleted": len(ids) if args.apply else 0,
        "ids": ids,
        "dry_run": bool(args.dry_run),
    }, indent=2))


def cmd_learn_embed_all(args):
    con = connect()
    init_db(con)
    if embeddings_disabled():
        print("embeddings skipped by environment")
        con.close()
        return
    if not has_learnings_vec(con) or not try_load_sqlite_vec(con):
        print("sqlite-vec not available")
        con.close()
        return
    rows = con.execute(
        "SELECT id, key, type, insight, tags FROM learnings WHERE embedding IS NULL"
    ).fetchall()
    count = 0
    for row_id, key, learning_type, insight, tags in rows:
        try:
            vec = embed(f"{key} {learning_type} {insight} {tags or ''}")
            con.execute("UPDATE learnings SET embedding = ? WHERE id = ?", (vec, row_id))
            con.execute(
                "INSERT OR REPLACE INTO learnings_vec(rowid, embedding) VALUES (?, ?)",
                (row_id, vec)
            )
            count += 1
            if count % 10 == 0:
                con.commit()
        except Exception:
            continue
    con.commit()
    con.close()
    print(f"Done. Backfilled {count} learnings.")


def cmd_learn_export(args):
    con = connect()
    init_db(con)
    rows = con.execute(f"{LEARNING_SELECT} ORDER BY learnings.created_at ASC").fetchall()
    con.close()
    for row in rows:
        item = learning_row_to_dict(row)
        item.pop("effective_confidence", None)
        item.pop("score", None)
        item.pop("method", None)
        print(json.dumps(item, sort_keys=True))


def cmd_learn_import(args):
    imported = 0
    rejected = 0
    con = connect()
    init_db(con)
    with open(args.file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                trusted = bool(item.get("trusted"))
                trusted_requested = bool(item.get("trusted_confirmed"))
                if trusted and item.get("source") != "user-stated" and not trusted_requested:
                    raise ValueError("trusted non-user-stated import requires trusted_confirmed")
                insert_learning(
                    con,
                    session_id=item.get("session_id") or "import",
                    project=item.get("project") or "global",
                    key=item.get("key"),
                    learning_type=item.get("type"),
                    insight=item.get("insight"),
                    confidence=item.get("confidence"),
                    source=item.get("source", "observed"),
                    trusted=trusted,
                    trusted_requested=trusted_requested,
                    tags=item.get("tags") or [],
                    files=item.get("files") or json.loads(item.get("files_json") or "[]"),
                    branch=item.get("branch"),
                    commit_sha=item.get("commit_sha"),
                    metadata=item.get("metadata") or json.loads(item.get("metadata_json") or "{}"),
                    created_at=item.get("created_at"),
                    updated_at=item.get("updated_at"),
                    embed_on_write=not args.no_embed,
                )
                imported += 1
            except Exception:
                rejected += 1
    con.close()
    print(json.dumps({"imported": imported, "rejected": rejected}, indent=2))


def observation_migration_candidates(con):
    rows = con.execute(
        "SELECT id, session_id, project, content, tags, created_at "
        "FROM observations ORDER BY created_at ASC"
    ).fetchall()
    candidates = []
    for obs_id, session_id, project, content, tags, created_at in rows:
        content = (content or "").strip()
        if len(content) < 40 or len(content) > 1000:
            continue
        if PROMPT_INJECTION_RE.search(content):
            continue
        key = slugify_key(content)
        candidates.append({
            "observation_id": obs_id,
            "session_id": session_id,
            "project": project,
            "key": key,
            "type": "operational",
            "insight": content,
            "confidence": 6,
            "source": "observed",
            "trusted": False,
            "tags": tags or "",
            "created_at": created_at,
        })
    return candidates


def cmd_learn_migrate_observations(args):
    if not args.dry_run and not args.apply:
        print(json.dumps({"error": "choose --dry-run or --apply"}), file=sys.stderr)
        sys.exit(2)
    con = connect()
    init_db(con)
    candidates = observation_migration_candidates(con)
    imported = 0
    if args.apply:
        for item in candidates:
            try:
                insert_learning(
                    con,
                    session_id=item["session_id"],
                    project=item["project"],
                    key=item["key"],
                    learning_type=item["type"],
                    insight=item["insight"],
                    confidence=item["confidence"],
                    source=item["source"],
                    trusted=False,
                    tags=item["tags"],
                    created_at=item["created_at"],
                    updated_at=item["created_at"],
                    metadata={"migrated_from_observation_id": item["observation_id"]},
                    embed_on_write=not args.no_embed,
                )
                imported += 1
            except Exception:
                continue
    con.close()
    print(json.dumps({
        "candidates": len(candidates),
        "imported": imported,
        "dry_run": bool(args.dry_run),
    }, indent=2))


def cmd_learn_context(args):
    con = connect()
    init_db(con)
    project = normalize_project(os.path.realpath(args.project)) if args.project else None
    context = learning_context(
        con,
        project=project,
        limit=args.limit,
        include_cross_project=args.cross_project,
    )
    con.close()
    count = sum(1 for line in context.splitlines() if line.startswith("["))
    print(json.dumps({"context": context, "count": count}))


def cmd_learn_config(args):
    if args.action == "show":
        print(json.dumps(load_config(), indent=2, sort_keys=True))
        return
    if not args.key or args.value is None:
        print(json.dumps({"error": "learn-config set requires key and value"}), file=sys.stderr)
        sys.exit(2)
    if args.key not in CONFIG_DEFAULTS:
        print(json.dumps({"error": f"unknown config key: {args.key}"}), file=sys.stderr)
        sys.exit(2)
    value = args.value.lower()
    if value in {"true", "1", "yes", "on"}:
        parsed = True
    elif value in {"false", "0", "no", "off"}:
        parsed = False
    else:
        try:
            parsed = int(args.value)
        except Exception:
            parsed = args.value
    cfg = save_config({args.key: parsed})
    print(json.dumps({args.key: cfg.get(args.key)}, indent=2))


def cmd_list(args):
    """List all observations with id, scope, date, content, tags."""
    project = normalize_project(get_project())
    con = connect()
    init_db(con)

    query = "SELECT id, project, created_at, content, tags FROM observations"
    params = []
    conditions = []

    if args.global_only:
        conditions.append("project = 'global'")
    elif args.project:
        p = normalize_project(args.project)
        conditions.append("(project = ? OR project = 'global')")
        params.append(p)
    elif not args.all:
        conditions.append("(project = ? OR project = 'global')")
        params.append(project)

    if args.tag:
        conditions.append("tags LIKE ?")
        params.append(f"%{args.tag}%")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY created_at DESC"

    if args.limit:
        query += f" LIMIT {args.limit}"

    rows = con.execute(query, params).fetchall()
    con.close()

    if not rows:
        print("No observations found.")
        return

    for obs_id, proj, created_at, content, tags in rows:
        scope = "[global] " if proj == "global" else "[project]"
        date = created_at[:10] if created_at else "?"
        print(f"{obs_id:>4}  {scope}  {date}  {content[:80]}")
        if tags:
            print(f"            tags: {tags}")


def cmd_prune(args):
    days = args.days or 90
    try:
        cutoff_str = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OverflowError:
        cutoff_str = "0001-01-01T00:00:00Z"

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
    p.add_argument("--no-embed", action="store_true")

    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--project", default=None)
    p.add_argument("--limit", type=int, default=5)

    sub.add_parser("stats")
    sub.add_parser("analytics")
    sub.add_parser("embed-all")

    p = sub.add_parser("prune")
    p.add_argument("--days", type=int, default=90)

    sub.add_parser("export")
    p = sub.add_parser("import")
    p.add_argument("file", help="Path to JSON file to import")

    p = sub.add_parser("list")
    p.add_argument("--global", dest="global_only", action="store_true",
                   help="Show only global observations")
    p.add_argument("--project", default=None,
                   help="Filter by project path")
    p.add_argument("--tag", default=None,
                   help="Filter by tag keyword")
    p.add_argument("--all", action="store_true",
                   help="Show all observations across all projects")
    p.add_argument("--limit", type=int, default=50,
                   help="Max results (default 50)")

    p = sub.add_parser("forget")
    p.add_argument("query", help="Search term to match observations for deletion")

    p = sub.add_parser("edit")
    p.add_argument("id", type=int, help="Observation ID to edit")
    p.add_argument("--content", default=None, help="New content")
    p.add_argument("--tags", default=None, help="New tags (comma-separated)")
    p.add_argument("--project", default=None, help="New project path or 'global'")

    p = sub.add_parser("learn-add")
    p.add_argument("--type", required=True, choices=sorted(LEARNING_TYPES))
    p.add_argument("--key", required=True)
    p.add_argument("--insight", required=True)
    p.add_argument("--confidence", type=int, default=None)
    p.add_argument("--source", choices=sorted(LEARNING_SOURCES), default="observed")
    p.add_argument("--trusted", action="store_true")
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--file", action="append", default=[])
    p.add_argument("--project", default=None)
    p.add_argument("--global", dest="global_scope", action="store_true")
    p.add_argument("--session-id", default=None)
    p.add_argument("--branch", default=None)
    p.add_argument("--commit-sha", default=None)
    p.add_argument("--metadata-json", default=None)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("learn-search")
    p.add_argument("query", nargs="+")
    p.add_argument("--type", choices=sorted(LEARNING_TYPES), default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--global", dest="global_scope", action="store_true")
    p.add_argument("--cross-project", action="store_true")
    p.add_argument("--trusted-only", action="store_true")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-decay", action="store_true")
    p.add_argument("--include-superseded", action="store_true")

    p = sub.add_parser("learn-list")
    p.add_argument("--type", choices=sorted(LEARNING_TYPES), default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--global", dest="global_scope", action="store_true")
    p.add_argument("--trusted-only", action="store_true")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("learn-show")
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("learn-forget")
    p.add_argument("query", nargs="*")
    p.add_argument("--id", type=int, default=None)
    p.add_argument("--key", default=None)
    p.add_argument("--type", choices=sorted(LEARNING_TYPES), default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--global", dest="global_scope", action="store_true")

    p = sub.add_parser("learn-promote")
    p.add_argument("--id", required=True, type=int)

    p = sub.add_parser("learn-demote")
    p.add_argument("--id", required=True, type=int)

    p = sub.add_parser("learn-stats")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("learn-prune")
    p.add_argument("--older-than-days", type=int, default=None)
    p.add_argument("--confidence-below", type=int, default=None)
    p.add_argument("--superseded", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")

    sub.add_parser("learn-embed-all")
    sub.add_parser("learn-export")

    p = sub.add_parser("learn-import")
    p.add_argument("file")
    p.add_argument("--no-embed", action="store_true")

    p = sub.add_parser("learn-migrate-observations")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-embed", action="store_true")

    p = sub.add_parser("learn-context")
    p.add_argument("--project", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--cross-project", action="store_true")

    p = sub.add_parser("learn-config")
    p.add_argument("action", choices=["show", "set"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")

    args = parser.parse_args()

    dispatch = {
        "init": cmd_init,
        "session-start": cmd_session_start,
        "session-end": cmd_session_end,
        "observe": cmd_observe,
        "search": cmd_search,
        "stats": cmd_stats,
        "analytics": cmd_analytics,
        "embed-all": cmd_embed_all,
        "prune": cmd_prune,
        "forget": cmd_forget,
        "edit": cmd_edit,
        "list": cmd_list,
        "export": cmd_export,
        "import": cmd_import,
        "learn-add": cmd_learn_add,
        "learn-search": cmd_learn_search,
        "learn-list": cmd_learn_list,
        "learn-show": cmd_learn_show,
        "learn-forget": cmd_learn_forget,
        "learn-promote": cmd_learn_promote,
        "learn-demote": cmd_learn_demote,
        "learn-stats": cmd_learn_stats,
        "learn-prune": cmd_learn_prune,
        "learn-embed-all": cmd_learn_embed_all,
        "learn-export": cmd_learn_export,
        "learn-import": cmd_learn_import,
        "learn-migrate-observations": cmd_learn_migrate_observations,
        "learn-context": cmd_learn_context,
        "learn-config": cmd_learn_config,
    }

    if args.cmd in dispatch:
        dispatch[args.cmd](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

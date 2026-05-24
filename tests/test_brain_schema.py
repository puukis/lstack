import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.db import connect
from brain.doctor import run_doctor
from brain.schema import (
    PHASE_1A_TABLES,
    PHASE_1B_TABLES,
    existing_tables,
    init_schema,
    missing_phase_1a_tables,
    missing_phase_1b_tables,
)


class TestBrainSchema(unittest.TestCase):
    def test_schema_initialization_creates_phase_1a_and_1b_tables_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            con = connect(db_path)
            tables = existing_tables(con)
            con.close()
            self.assertTrue(PHASE_1A_TABLES.issubset(tables))
            self.assertTrue(PHASE_1B_TABLES.issubset(tables))
            self.assertNotIn("brain_contracts", tables)
            self.assertNotIn("brain_contract_events", tables)
            self.assertNotIn("brain_receipts", tables)
            self.assertNotIn("brain_blackbox_events", tables)
            self.assertNotIn("brain_handoffs", tables)
            self.assertNotIn("brain_artifacts", tables)

    def test_schema_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            con = connect(db_path)
            init_schema(con)
            decision_cols = {row[1] for row in con.execute("PRAGMA table_info(brain_decisions)").fetchall()}
            candidate_cols = {row[1] for row in con.execute("PRAGMA table_info(brain_memory_candidates)").fetchall()}
            self.assertEqual(missing_phase_1a_tables(con), [])
            self.assertEqual(missing_phase_1b_tables(con), [])
            self.assertIn("scope", decision_cols)
            self.assertIn("scope", candidate_cols)
            con.close()

    def test_existing_phase_1a_data_survives_phase_1b_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            con = sqlite3.connect(str(db_path))
            con.execute(
                """
                CREATE TABLE brain_projects (
                    id INTEGER PRIMARY KEY,
                    root_path_hash TEXT NOT NULL,
                    root_path_display TEXT,
                    repo_id TEXT,
                    git_remote_hash TEXT,
                    git_branch TEXT,
                    name TEXT,
                    platform TEXT,
                    shell_mode TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(root_path_hash)
                )
                """
            )
            con.execute(
                """
                INSERT INTO brain_projects (
                    root_path_hash, root_path_display, name, platform, shell_mode, created_at, updated_at
                ) VALUES ('hash', '/tmp/repo', 'repo', 'linux', 'bash', 'now', 'now')
                """
            )
            con.commit()
            init_schema(con)
            row = con.execute("SELECT name FROM brain_projects WHERE root_path_hash = 'hash'").fetchone()
            tables = existing_tables(con)
            con.close()
            self.assertEqual(row[0], "repo")
            self.assertTrue(PHASE_1B_TABLES.issubset(tables))

    def test_scope_columns_are_added_to_existing_phase1b_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            con = sqlite3.connect(str(db_path))
            con.execute(
                """
                CREATE TABLE brain_decisions (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER,
                    key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT,
                    enforcement_hint TEXT,
                    applies_to_json TEXT NOT NULL,
                    forbidden_patterns_json TEXT NOT NULL,
                    required_patterns_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    privacy_class TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    supersedes_key TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE brain_memory_candidates (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER,
                    candidate_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    rationale TEXT,
                    proposed_target TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    confidence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    privacy_class TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    promoted_to_type TEXT,
                    promoted_to_id INTEGER
                )
                """
            )
            init_schema(con)
            decision_cols = {row[1] for row in con.execute("PRAGMA table_info(brain_decisions)").fetchall()}
            candidate_cols = {row[1] for row in con.execute("PRAGMA table_info(brain_memory_candidates)").fetchall()}
            con.close()
            self.assertIn("scope", decision_cols)
            self.assertIn("scope", candidate_cols)

    def test_doctor_reports_corrupt_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            db_path.write_text("not sqlite", encoding="utf-8")
            result = run_doctor(db_path)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["checks"][0]["id"], "db.reachable")

    def test_doctor_reports_missing_tables_without_creating_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            con = sqlite3.connect(str(db_path))
            con.execute("CREATE TABLE existing_table (id INTEGER PRIMARY KEY)")
            con.close()
            result = run_doctor(db_path)
            self.assertEqual(result["status"], "fail")
            table_check = next(c for c in result["checks"] if c["id"] == "schema.tables")
            self.assertIn("lstack brain status", table_check["message"])
            phase1b_check = next(c for c in result["checks"] if c["id"] == "schema.phase1b")
            self.assertIn("Phase 1B", phase1b_check["message"])
            con = sqlite3.connect(str(db_path))
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            con.close()
            self.assertFalse(PHASE_1A_TABLES & tables)
            self.assertFalse(PHASE_1B_TABLES & tables)


if __name__ == "__main__":
    unittest.main()

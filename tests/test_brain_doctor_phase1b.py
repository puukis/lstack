import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.capture import upsert_candidate
from brain.db import connect, ensure_project
from brain.decisions import add_decision
from brain.doctor import run_doctor
from brain.schema import init_schema


class TestBrainDoctorPhase1B(unittest.TestCase):
    def test_doctor_reports_phase1b_counts_and_decision_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / "bad.sh").write_text("python3 bad.py\n", encoding="utf-8")
            db_path = root / "lstack.db"
            con = connect(db_path)
            project = ensure_project(con, root)
            add_decision(
                con,
                project["id"],
                key="runtime-python-provider",
                title="Use runtime",
                decision="Use run_python.",
                forbidden_patterns=["python3 "],
                applies_to=["scripts/*.sh"],
                confidence=9,
            )
            upsert_candidate(
                con,
                project["id"],
                "implementation_decision",
                "pending",
                "Pending",
                "Pending candidate",
                proposed_target="brain_decisions",
                confidence=6,
            )
            con.close()
            cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                result = run_doctor(db_path)
            finally:
                os.chdir(cwd)
            checks = {item["id"]: item for item in result["checks"]}
            self.assertIn("decisions.active_count", checks)
            self.assertIn("capture.pending_candidates", checks)
            self.assertIn("decisions.check", checks)
            self.assertIn("autolearn.enabled", checks)
            self.assertIn("autolearn.hook_wrapper", checks)
            self.assertNotIn("hooks.capture", checks)
            self.assertIn("Decision violations: 1", checks["decisions.check"]["message"])

    def test_doctor_reports_missing_phase1b_tables_without_mutating(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            con = sqlite3.connect(str(db_path))
            con.execute("CREATE TABLE brain_projects (id INTEGER PRIMARY KEY)")
            con.close()
            result = run_doctor(db_path)
            checks = {item["id"]: item for item in result["checks"]}
            self.assertEqual(checks["schema.capture"]["status"], "fail")
            con = sqlite3.connect(str(db_path))
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            con.close()
            self.assertNotIn("brain_decisions", tables)


if __name__ == "__main__":
    unittest.main()

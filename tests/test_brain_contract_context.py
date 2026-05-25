"""Tests for LBrain Task Contracts: contract context integration."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.contracts import close_contract, complete_contract, create_contract
from brain.context import build_context
from brain.db import connect, ensure_project


def _db(tmp):
    db_path = Path(tmp) / "test.db"
    con = connect(db_path)
    project = ensure_project(con, Path(tmp))
    return con, project


class TestContractContext(unittest.TestCase):
    def test_active_contract_appears_in_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            create_contract(
                con, project["id"],
                task_goal="Fix the test failure",
                allowed_files=["lbrain/**", "tests/test_brain_context.py"],
                forbidden_files=["install.sh"],
                required_tests=["py -3 -m unittest tests.test_brain_context -v"],
                mode="warn",
            )
            text = build_context(con, project, target="codex")
            con.close()
            self.assertIn("Fix the test failure", text)
            self.assertIn("lbrain/**", text)
            self.assertIn("install.sh", text)

    def test_no_active_contract_gives_clean_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            text = build_context(con, project, target="codex")
            con.close()
            self.assertNotIn("Active task contract", text)

    def test_closed_contract_not_in_normal_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Closed task goal")
            close_contract(con, c["id"], project["id"])
            text = build_context(con, project, target="codex")
            con.close()
            self.assertNotIn("Closed task goal", text)

    def test_completed_contract_not_in_normal_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Completed task goal")
            complete_contract(con, c["id"], project["id"])
            text = build_context(con, project, target="codex")
            con.close()
            self.assertNotIn("Completed task goal", text)

    def test_contract_from_another_project_not_in_context(self):
        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            con_a = connect(Path(tmp_a) / "test.db")
            con_b = connect(Path(tmp_b) / "test.db")
            proj_a = ensure_project(con_a, Path(tmp_a))
            proj_b = ensure_project(con_b, Path(tmp_b))
            create_contract(con_a, proj_a["id"], task_goal="Project A unique goal")
            text_b = build_context(con_b, proj_b, target="codex")
            con_a.close()
            con_b.close()
            self.assertNotIn("Project A unique goal", text_b)

    def test_context_includes_required_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            create_contract(
                con, project["id"],
                task_goal="Task with test",
                required_tests=["py -3 -m unittest discover -s tests -v"],
            )
            text = build_context(con, project, target="codex")
            con.close()
            self.assertIn("py -3 -m unittest discover", text)

    def test_context_includes_forbidden_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            create_contract(
                con, project["id"],
                task_goal="Scoped task",
                forbidden_files=["secrets.env", "config/prod/**"],
            )
            text = build_context(con, project, target="codex")
            con.close()
            self.assertIn("secrets.env", text)

    def test_context_is_compact_no_raw_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            create_contract(
                con, project["id"],
                task_goal="Task",
                allowed_files=["src/**"],
            )
            text = build_context(con, project, target="codex")
            con.close()
            self.assertLess(len(text), 8000)

    def test_explain_shows_included_contract_and_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Active task")
            close_contract(con, c["id"], project["id"])
            create_contract(con, project["id"], task_goal="New active task")
            explained = build_context(con, project, target="codex", explain=True)
            con.close()
            self.assertIn("contract", explained)
            self.assertIn("New active task", explained)

    def test_json_mode_includes_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            create_contract(con, project["id"], task_goal="JSON contract task")
            result = build_context(con, project, target="codex", json_mode=True)
            con.close()
            included_types = [i["type"] for i in result["included"]]
            self.assertIn("contract", included_types)
            contract_item = next(i for i in result["included"] if i["type"] == "contract")
            self.assertIn("JSON contract task", contract_item["text"])

    def test_json_mode_no_contract_has_skipped_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            result = build_context(con, project, target="codex", json_mode=True)
            con.close()
            skipped_types = [s["type"] for s in result["skipped"]]
            self.assertIn("contract", skipped_types)


if __name__ == "__main__":
    unittest.main()

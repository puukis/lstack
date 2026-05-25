"""Tests for LBrain Task Contracts: contract generalization and cross-platform."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.contracts import (
    create_contract,
    close_contract,
    complete_contract,
    get_active_contract,
    normalize_input_path,
    run_contract_check,
    _match_pattern,
    _check_path,
)
from brain.context import build_context
from brain.db import connect, ensure_project


def _db(tmp):
    db_path = Path(tmp) / "test.db"
    con = connect(db_path)
    project = ensure_project(con, Path(tmp))
    return con, project


class TestContractGeneralization(unittest.TestCase):
    def test_random_node_repo_can_create_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8"
            )
            con = connect(root / "test.db")
            project = ensure_project(con, root)
            c = create_contract(
                con, project["id"],
                task_goal="Fix Node test",
                allowed_files=["src/**", "tests/**"],
                mode="warn",
            )
            self.assertIsNotNone(c)
            self.assertEqual(c["status"], "active")
            active = get_active_contract(con, project["id"])
            self.assertIsNotNone(active)
            con.close()

    def test_random_python_repo_can_create_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "setup.py").write_text("from setuptools import setup; setup(name='foo')")
            (root / "src").mkdir()
            con = connect(root / "test.db")
            project = ensure_project(con, root)
            c = create_contract(
                con, project["id"],
                task_goal="Add feature",
                allowed_files=["src/**"],
                forbidden_files=["setup.py"],
                mode="warn",
            )
            self.assertEqual(c["task_goal"], "Add feature")
            result = run_contract_check(con, c, paths=["src/foo.py"])
            self.assertEqual(result["status"], "pass")
            result2 = run_contract_check(con, c, paths=["setup.py"])
            self.assertNotEqual(result2["status"], "pass")
            con.close()

    def test_no_lstack_specific_contract_in_random_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            con = connect(root / "test.db")
            project = ensure_project(con, root)
            text = build_context(con, project, target="codex")
            con.close()
            self.assertNotIn("lbrain/**", text)
            self.assertNotIn("install.sh", text)
            self.assertNotIn("hooks/*.sh", text)

    def test_project_a_contract_not_in_project_b(self):
        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            con_a = connect(Path(tmp_a) / "test.db")
            con_b = connect(Path(tmp_b) / "test.db")
            proj_a = ensure_project(con_a, Path(tmp_a))
            proj_b = ensure_project(con_b, Path(tmp_b))
            create_contract(con_a, proj_a["id"], task_goal="Secret A task")
            text_b = build_context(con_b, proj_b, target="codex")
            active_b = get_active_contract(con_b, proj_b["id"])
            con_a.close()
            con_b.close()
            self.assertNotIn("Secret A task", text_b)
            self.assertIsNone(active_b)

    def test_no_user_global_contracts_in_phase1c(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Task")
            self.assertIsNotNone(c.get("project_id"))
            contracts = con.execute(
                "SELECT COUNT(*) FROM brain_contracts WHERE project_id IS NULL"
            ).fetchone()[0]
            con.close()
            self.assertEqual(contracts, 0)

    def test_no_active_templates_in_phase1c(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            contracts = con.execute(
                "SELECT COUNT(*) FROM brain_contracts WHERE status = 'active'"
            ).fetchone()[0]
            con.close()
            self.assertEqual(contracts, 0)

    def test_closed_contracts_not_leaked_to_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Top secret closed task")
            close_contract(con, c["id"], project["id"])
            text = build_context(con, project, target="codex")
            result = build_context(con, project, target="codex", json_mode=True)
            con.close()
            self.assertNotIn("Top secret closed task", text)
            included_goals = [
                i.get("text", "") for i in result["included"]
                if i["type"] == "contract"
            ]
            self.assertFalse(any("Top secret closed task" in g for g in included_goals))

    def test_completed_contracts_not_leaked_to_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Completed secret task")
            complete_contract(con, c["id"], project["id"])
            text = build_context(con, project, target="codex")
            con.close()
            self.assertNotIn("Completed secret task", text)

    def test_fake_lstack_repo_does_not_leak_lstack_specifics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Fake lstack signals
            (root / "bin").mkdir()
            (root / "bin" / "lstack").write_text("#!/bin/bash\necho test\n")
            (root / "lbrain").mkdir()
            (root / "lbrain" / "brain.py").write_text("# brain\n")
            con = connect(root / "test.db")
            project = ensure_project(con, root)
            text = build_context(con, project, target="codex")
            con.close()
            self.assertNotIn("Active task contract", text)


class TestCrossplatformPaths(unittest.TestCase):
    def test_relative_path_unchanged(self):
        rel = normalize_input_path("docs/lbrain.md")
        self.assertEqual(rel, "docs/lbrain.md")

    def test_backslash_path_normalized(self):
        rel = normalize_input_path(r"docs\lbrain.md")
        self.assertNotIn("\\", rel)

    def test_windows_absolute_to_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            file_path = root / "src" / "main.py"
            file_path.parent.mkdir(exist_ok=True)
            file_path.touch()
            abs_str = str(file_path)
            rel = normalize_input_path(abs_str, root)
            self.assertEqual(rel, "src/main.py")

    def test_path_with_spaces(self):
        result = normalize_input_path("work space/docs/readme.md")
        self.assertIn("docs", result)

    def test_match_with_spaces_in_path(self):
        self.assertTrue(_match_pattern("work space/docs/readme.md", "work space/docs/**"))

    def test_msys2_path_form(self):
        rel = normalize_input_path("/c/Users/name/repo/file.py")
        self.assertIn("file.py", rel)

    def test_check_path_msys2_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "docs").mkdir(exist_ok=True)
            target = root / "docs" / "readme.md"
            target.touch()
            root_str = str(root).replace("\\", "/")
            file_str = str(target).replace("\\", "/")
            decision, reason = _check_path(
                file_str,
                allowed_files=["docs/**"],
                forbidden_files=[],
                project_root=root,
            )
            self.assertEqual(decision, "allow")

    def test_forbidden_path_windows_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "secrets.env").touch()
            file_str = str(root / "secrets.env").replace("\\", "/")
            decision, reason = _check_path(
                file_str,
                allowed_files=[],
                forbidden_files=["secrets.env"],
                project_root=root,
            )
            self.assertEqual(decision, "deny")


class TestDoctorPhase1C(unittest.TestCase):
    def test_doctor_contract_check_with_active_contract(self):
        import os
        from brain.doctor import run_doctor
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "test.db"
            con = connect(db_path)
            project = ensure_project(con, root)
            create_contract(con, project["id"], task_goal="Doctor test task", mode="warn")
            con.close()
            cwd = Path.cwd()
            try:
                os.chdir(root)
                result = run_doctor(db_path)
            finally:
                os.chdir(cwd)
            checks = {c["id"]: c for c in result["checks"]}
            self.assertIn("contracts.active", checks)
            self.assertIn("contracts.violations", checks)
            self.assertIn("#", checks["contracts.active"]["message"])
            self.assertIn("mode=warn", checks["contracts.active"]["message"])

    def test_doctor_no_active_contract_is_not_failure(self):
        import os
        from brain.doctor import run_doctor
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "test.db"
            con = connect(db_path)
            ensure_project(con, root)
            con.close()
            cwd = Path.cwd()
            try:
                os.chdir(root)
                result = run_doctor(db_path)
            finally:
                os.chdir(cwd)
            checks = {c["id"]: c for c in result["checks"]}
            self.assertIn("contracts.active", checks)
            self.assertIn(checks["contracts.active"]["status"], ("pass", "warn"))

    def test_doctor_phase1c_tables_reported(self):
        import os
        from brain.doctor import run_doctor
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "test.db"
            con = connect(db_path)
            con.close()
            cwd = Path.cwd()
            try:
                os.chdir(root)
                result = run_doctor(db_path)
            finally:
                os.chdir(cwd)
            checks = {c["id"]: c for c in result["checks"]}
            self.assertIn("schema.task_contracts", checks)
            self.assertEqual(checks["schema.task_contracts"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()

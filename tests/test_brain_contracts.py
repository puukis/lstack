"""Tests for LBrain Task Contracts."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.contracts import (
    close_contract,
    complete_contract,
    create_contract,
    explain_contract,
    get_active_contract,
    get_contract,
    list_contracts,
    normalize_input_path,
    record_test,
    render_check_result,
    render_contract_status,
    run_contract_check,
    _match_pattern,
    _check_path,
    _check_command,
)
from brain.db import connect, ensure_project


def _db(tmp):
    db_path = Path(tmp) / "test.db"
    con = connect(db_path)
    project = ensure_project(con, Path(tmp))
    return con, project


class TestContractCreate(unittest.TestCase):
    def test_create_basic(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Fix the bug", mode="warn")
            self.assertIsNotNone(c)
            self.assertEqual(c["task_goal"], "Fix the bug")
            self.assertEqual(c["mode"], "warn")
            self.assertEqual(c["status"], "active")
            con.close()

    def test_create_with_all_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con,
                project["id"],
                task_goal="Update docs",
                title="Docs task",
                mode="strict",
                allowed_files=["docs/**"],
                forbidden_files=["lbrain/**", "install.sh"],
                required_tests=["py -3 -m unittest discover -s tests -v"],
                stop_conditions=["scope requires changing packaging"],
                review_checklist=["Verify docs render correctly"],
                max_files_changed=3,
            )
            self.assertEqual(c["mode"], "strict")
            self.assertEqual(c["title"], "Docs task")
            self.assertIn("docs/**", c["allowed_files"])
            self.assertIn("install.sh", c["forbidden_files"])
            self.assertIn("py -3 -m unittest discover -s tests -v", c["required_tests"])
            self.assertEqual(c["max_files_changed"], 3)
            con.close()

    def test_create_default_mode_is_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Task")
            self.assertEqual(c["mode"], "warn")
            con.close()

    def test_create_refuses_second_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            create_contract(con, project["id"], task_goal="First")
            with self.assertRaises(ValueError) as ctx:
                create_contract(con, project["id"], task_goal="Second")
            self.assertIn("active contract", str(ctx.exception))
            con.close()

    def test_create_replace_closes_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            first = create_contract(con, project["id"], task_goal="First")
            second = create_contract(con, project["id"], task_goal="Second", replace=True)
            closed = get_contract(con, first["id"])
            self.assertEqual(closed["status"], "closed")
            self.assertEqual(second["status"], "active")
            active = get_active_contract(con, project["id"])
            self.assertEqual(active["id"], second["id"])
            con.close()

    def test_create_invalid_mode_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            with self.assertRaises(ValueError):
                create_contract(con, project["id"], task_goal="Task", mode="bad")
            con.close()

    def test_get_active_contract_none_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            result = get_active_contract(con, project["id"])
            self.assertIsNone(result)
            con.close()

    def test_list_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            create_contract(con, project["id"], task_goal="First")
            items = list_contracts(con, project["id"])
            self.assertEqual(len(items), 1)
            con.close()

    def test_list_contracts_filter_by_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="First")
            close_contract(con, c["id"], project["id"])
            active = list_contracts(con, project["id"], status="active")
            closed = list_contracts(con, project["id"], status="closed")
            self.assertEqual(len(active), 0)
            self.assertEqual(len(closed), 1)
            con.close()


class TestContractClose(unittest.TestCase):
    def test_close_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Task")
            closed = close_contract(con, c["id"], project["id"])
            self.assertEqual(closed["status"], "closed")
            self.assertIsNotNone(closed["closed_at"])
            active = get_active_contract(con, project["id"])
            self.assertIsNone(active)
            con.close()

    def test_close_returns_none_for_wrong_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Task")
            result = close_contract(con, c["id"], project_id=9999)
            self.assertIsNone(result)
            con.close()


class TestContractComplete(unittest.TestCase):
    def test_complete_no_warnings_when_tests_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                required_tests=["py -3 -m unittest discover"],
            )
            record_test(con, c["id"], project["id"], command="py -3 -m unittest discover", result="pass")
            completed, warnings = complete_contract(con, c["id"], project["id"])
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(warnings, [])
            con.close()

    def test_complete_warns_if_required_tests_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                required_tests=["py -3 -m unittest discover"],
            )
            completed, warnings = complete_contract(con, c["id"], project["id"])
            self.assertEqual(completed["status"], "completed")
            self.assertTrue(any("Required tests not recorded" in w for w in warnings))
            con.close()

    def test_complete_warns_strict_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task", mode="strict",
                forbidden_files=["install.sh"],
            )
            run_contract_check(con, c, paths=["install.sh"])
            c = get_contract(con, c["id"])
            _, warnings = complete_contract(con, c["id"], project["id"])
            self.assertTrue(any("violation" in w.lower() for w in warnings))
            con.close()

    def test_complete_not_found_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            result, _ = complete_contract(con, 9999, project["id"])
            self.assertIsNone(result)
            con.close()


class TestRecordTest(unittest.TestCase):
    def test_record_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                required_tests=["py -3 -m unittest discover"],
            )
            updated = record_test(
                con, c["id"], project["id"],
                command="py -3 -m unittest discover",
                result="pass",
            )
            self.assertEqual(len(updated["recorded_tests"]), 1)
            self.assertEqual(updated["recorded_tests"][0]["result"], "pass")
            con.close()

    def test_record_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Task")
            updated = record_test(
                con, c["id"], project["id"],
                command="some-test",
                result="fail",
                summary="3 tests failed",
            )
            self.assertEqual(updated["recorded_tests"][0]["result"], "fail")
            self.assertEqual(updated["recorded_tests"][0]["summary"], "3 tests failed")
            con.close()

    def test_record_does_not_execute_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Task")
            updated = record_test(
                con, c["id"], project["id"],
                command="rm -rf /",
                result="unknown",
            )
            self.assertIsNotNone(updated)
            con.close()

    def test_status_shows_recorded_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                required_tests=["run-tests"],
            )
            record_test(con, c["id"], project["id"], command="run-tests", result="pass")
            c2 = get_contract(con, c["id"])
            text = render_contract_status(c2)
            self.assertIn("run-tests", text)
            self.assertIn("pass", text)
            con.close()


class TestPathMatching(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(_match_pattern("package.json", "package.json"))

    def test_wildcard_glob(self):
        self.assertTrue(_match_pattern("tests/test_foo.py", "tests/*.py"))

    def test_double_star_glob(self):
        self.assertTrue(_match_pattern("lbrain/brain/context.py", "lbrain/**"))
        self.assertTrue(_match_pattern("docs/lbrain.md", "docs/**"))

    def test_no_match(self):
        self.assertFalse(_match_pattern("install.sh", "docs/**"))
        self.assertFalse(_match_pattern("src/foo.py", "tests/**"))

    def test_forbidden_beats_allowed(self):
        decision, reason = _check_path(
            "install.sh",
            allowed_files=["install.sh"],
            forbidden_files=["install.sh"],
        )
        self.assertEqual(decision, "deny")
        self.assertIn("forbidden", reason)

    def test_allowed_list_restricts_out_of_scope(self):
        decision, reason = _check_path(
            "lbrain/brain/context.py",
            allowed_files=["docs/**"],
            forbidden_files=[],
        )
        self.assertEqual(decision, "deny")

    def test_no_restrictions_allows_all(self):
        decision, _ = _check_path("anything.py", allowed_files=[], forbidden_files=[])
        self.assertEqual(decision, "allow")

    def test_missing_path_handled_gracefully(self):
        decision, _ = _check_path(None, allowed_files=["docs/**"], forbidden_files=[])
        self.assertEqual(decision, "allow")

    def test_windows_backslash_path(self):
        rel = normalize_input_path(r"docs\lbrain.md")
        self.assertNotIn("\\", rel)

    def test_windows_c_drive_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            test_file = root / "docs" / "readme.md"
            test_file.parent.mkdir(exist_ok=True)
            test_file.touch()
            abs_str = str(test_file).replace("\\", "/")
            rel = normalize_input_path(abs_str, root)
            self.assertEqual(rel, "docs/readme.md")

    def test_path_with_spaces(self):
        decision, _ = _check_path(
            "work space/docs/readme.md",
            allowed_files=["work space/docs/**"],
            forbidden_files=[],
        )
        self.assertEqual(decision, "allow")


class TestCommandMatching(unittest.TestCase):
    def test_allowed_command(self):
        decision, _ = _check_command("py -3 -m unittest", ["py -3"], [])
        self.assertEqual(decision, "allow")

    def test_forbidden_command(self):
        decision, reason = _check_command("rm -rf /", [], ["rm -rf"])
        self.assertEqual(decision, "deny")
        self.assertIn("forbidden", reason)

    def test_forbidden_beats_allowed(self):
        decision, _ = _check_command("rm -rf /", ["rm -rf"], ["rm -rf"])
        self.assertEqual(decision, "deny")

    def test_out_of_scope_command_is_warn(self):
        decision, _ = _check_command("npm install", ["py -3"], [])
        self.assertEqual(decision, "warn")

    def test_no_restrictions_allows(self):
        decision, _ = _check_command("anything", [], [])
        self.assertEqual(decision, "allow")

    def test_redaction_applied(self):
        decision, _ = _check_command("curl -H 'Authorization: Bearer abc.def.ghi' url", [], [])
        self.assertEqual(decision, "allow")


class TestContractModes(unittest.TestCase):
    def test_off_mode_no_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                mode="off", forbidden_files=["install.sh"],
            )
            result = run_contract_check(con, c, paths=["install.sh"])
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["violations"], [])
            con.close()

    def test_warn_mode_reports_warnings_not_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                mode="warn", forbidden_files=["install.sh"],
            )
            result = run_contract_check(con, c, paths=["install.sh"])
            self.assertEqual(result["status"], "warn")
            self.assertEqual(result["violations"], [])
            self.assertTrue(len(result["warnings"]) > 0)
            con.close()

    def test_strict_mode_returns_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                mode="strict", forbidden_files=["install.sh"],
            )
            result = run_contract_check(con, c, paths=["install.sh"])
            self.assertEqual(result["status"], "violation")
            self.assertTrue(len(result["violations"]) > 0)
            con.close()

    def test_no_contract_is_healthy_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            contract = get_active_contract(con, project["id"])
            self.assertIsNone(contract)
            con.close()

    def test_allowed_path_passes_in_all_modes(self):
        for mode in ("off", "warn", "strict"):
            with tempfile.TemporaryDirectory() as tmp:
                con, project = _db(tmp)
                c = create_contract(
                    con, project["id"], task_goal="Task",
                    mode=mode, allowed_files=["docs/**"],
                )
                result = run_contract_check(con, c, paths=["docs/readme.md"])
                self.assertNotIn("docs/readme.md", " ".join(result["warnings"] + result["violations"]))
                con.close()


class TestExplain(unittest.TestCase):
    def test_explain_allowed_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Update docs",
                allowed_files=["docs/**"], forbidden_files=["lbrain/**"],
            )
            text = explain_contract(c, path="docs/readme.md")
            self.assertIn("allow", text)
            self.assertIn("docs/readme.md", text)
            con.close()

    def test_explain_forbidden_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Update docs",
                allowed_files=["docs/**"], forbidden_files=["install.sh"],
            )
            text = explain_contract(c, path="install.sh")
            self.assertIn("deny", text)
            self.assertIn("install.sh", text)
            con.close()

    def test_explain_out_of_scope_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Update docs",
                allowed_files=["docs/**"],
            )
            text = explain_contract(c, path="lbrain/brain/context.py")
            self.assertIn("deny", text)
            con.close()

    def test_explain_required_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                required_tests=["py -3 -m unittest discover"],
            )
            text = explain_contract(c)
            self.assertIn("NOT YET RECORDED", text)
            con.close()

    def test_explain_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                forbidden_files=["install.sh"],
            )
            explain_contract(c, path="install.sh")
            c2 = get_contract(con, c["id"])
            self.assertEqual(c2["violation_count"], 0)
            con.close()


class TestJsonOutput(unittest.TestCase):
    def test_create_contract_is_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                allowed_files=["docs/**"],
            )
            serialized = json.dumps(c)
            loaded = json.loads(serialized)
            self.assertEqual(loaded["task_goal"], "Task")
            con.close()

    def test_list_contracts_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            create_contract(con, project["id"], task_goal="Task A")
            items = list_contracts(con, project["id"])
            serialized = json.dumps({"contracts": items})
            self.assertIn("Task A", serialized)
            con.close()

    def test_check_result_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(
                con, project["id"], task_goal="Task",
                forbidden_files=["bad.sh"],
            )
            result = run_contract_check(con, c, paths=["bad.sh"])
            serialized = json.dumps(result)
            loaded = json.loads(serialized)
            self.assertEqual(loaded["mode"], "warn")
            con.close()


class TestProjectScoping(unittest.TestCase):
    def test_contract_from_project_a_not_visible_in_project_b(self):
        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            con_a = connect(Path(tmp_a) / "test.db")
            con_b = connect(Path(tmp_b) / "test.db")
            proj_a = ensure_project(con_a, Path(tmp_a))
            proj_b = ensure_project(con_b, Path(tmp_b))
            create_contract(con_a, proj_a["id"], task_goal="Project A task")
            active_b = get_active_contract(con_b, proj_b["id"])
            con_a.close()
            con_b.close()
            self.assertIsNone(active_b)

    def test_no_user_global_contracts_in_phase1c(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = _db(tmp)
            c = create_contract(con, project["id"], task_goal="Task")
            self.assertIsNotNone(c["project_id"])
            con.close()


if __name__ == "__main__":
    unittest.main()

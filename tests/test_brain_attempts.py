import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.attempts import add_attempt, command_fingerprint, list_attempts, search_attempts
from brain.db import connect, ensure_project


class TestBrainAttempts(unittest.TestCase):
    def make_db(self, tmp):
        con = connect(Path(tmp) / "lstack.db")
        project = ensure_project(con, tmp)
        return con, project

    def test_add_list_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            add_attempt(
                con,
                project["id"],
                attempted_action="Tried python3 in Git Bash",
                command="python3 script.py",
                error_summary="python3 not found",
                why_failed="python3 is not on PATH",
                replacement_approach="Use py -3",
                retry_policy="ask",
                confidence=9,
            )
            self.assertEqual(len(list_attempts(con, project["id"])), 1)
            found = search_attempts(con, project["id"], "python3")
            con.close()
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["replacement_approach"], "Use py -3")

    def test_command_fingerprint_stable(self):
        self.assertEqual(command_fingerprint("python3  script.py"), command_fingerprint("python3 script.py"))

    def test_retry_policy_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            with self.assertRaises(ValueError):
                add_attempt(con, project["id"], "bad", retry_policy="retry", confidence=5)
            con.close()

    def test_invalid_confidence_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            with self.assertRaises(ValueError):
                add_attempt(con, project["id"], "bad", retry_policy="ask", confidence=11)
            con.close()

    def test_secret_redacted_before_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            item = add_attempt(
                con,
                project["id"],
                "Token failed",
                command="curl -H 'Authorization: Bearer abc.def.ghi'",
                error_summary="GITHUB_TOKEN=ghp_fakefakefake",
                retry_policy="ask",
                confidence=8,
            )
            con.close()
            self.assertEqual(item["redaction_status"], "redacted")
            self.assertIn("<redacted>", item["command_redacted"])
            self.assertIn("<redacted>", item["error_summary"])


if __name__ == "__main__":
    unittest.main()


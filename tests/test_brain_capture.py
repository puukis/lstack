import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.capture import (
    approve_candidate,
    capture_status,
    get_candidate,
    list_candidates,
    promote_candidate,
    record_event,
    reject_candidate,
    upsert_candidate,
)
from brain.db import connect, ensure_project
from brain.decisions import get_decision
from brain.attempts import list_attempts


class TestBrainCapture(unittest.TestCase):
    def make_db(self, root):
        con = connect(Path(root) / "lstack.db")
        project = ensure_project(con, root)
        return con, project

    def test_failed_command_repeated_creates_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            one = record_event(
                con,
                project["id"],
                "failed_command",
                "python3 was not found",
                command="python3 scripts/db.py stats",
                confidence_delta=2,
            )
            self.assertIsNone(one["candidate"])
            two = record_event(
                con,
                project["id"],
                "failed_command",
                "python3 was not found again",
                command="python3 scripts/db.py stats",
                confidence_delta=2,
            )
            con.close()
            self.assertIsNotNone(two["candidate"])
            self.assertEqual(two["candidate"]["candidate_type"], "failed_attempt")
            self.assertGreaterEqual(two["candidate"]["confidence"], 5)

    def test_user_correction_auto_promotes_explicit_lstack_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            result = record_event(
                con,
                project["id"],
                "user_correction",
                "do not use normal python again in lstack; use run_python",
                source="user",
            )
            decision = get_decision(con, project["id"], "runtime-python-provider")
            con.close()
            self.assertEqual(result["candidate"]["status"], "promoted")
            self.assertIsNotNone(decision)
            self.assertEqual(decision["status"], "active")

    def test_vague_python_correction_does_not_create_lstack_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            result = record_event(
                con,
                project["id"],
                "user_correction",
                "do not use normal python again",
                source="user",
            )
            decision = get_decision(con, project["id"], "runtime-python-provider")
            con.close()
            self.assertIsNotNone(result["candidate"])
            self.assertEqual(result["candidate"]["status"], "pending")
            self.assertIsNone(decision)

    def test_platform_fact_stays_candidate_until_explicitly_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            result = record_event(
                con,
                project["id"],
                "platform_detection",
                "Windows Git Bash detected",
                evidence={"os": "windows", "shell_mode": "git-bash"},
                source="detected",
            )
            decision = get_decision(con, project["id"], "git-bash-not-wsl")
            con.close()
            self.assertIsNotNone(result["candidate"])
            self.assertEqual(result["candidate"]["status"], "pending")
            self.assertIsNone(decision)

    def test_low_confidence_one_off_failure_stays_event_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            record_event(con, project["id"], "failed_command", "one-off failure", command="false")
            status = capture_status(con, project["id"])
            con.close()
            self.assertEqual(status["events"], 1)
            self.assertEqual(status["pending_candidates"], 0)

    def test_secret_correction_does_not_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            result = record_event(
                con,
                project["id"],
                "user_correction",
                "do not use normal python again GITHUB_TOKEN=ghp_fakefakefake",
                source="user",
            )
            decision = get_decision(con, project["id"], "runtime-python-provider")
            con.close()
            self.assertEqual(result["candidate"]["status"], "pending")
            self.assertEqual(result["candidate"]["redaction_status"], "suspect")
            self.assertIsNone(decision)

    def test_candidate_approve_reject_and_promote_to_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            candidate = upsert_candidate(
                con,
                project["id"],
                "implementation_decision",
                "use-tool",
                "Use tool",
                "Use the stable helper.",
                proposed_target="brain_decisions",
                evidence={"decision_fields": {"applies_to": ["scripts/*.sh"], "required_patterns": ["helper"]}},
                confidence=8,
            )
            approved = approve_candidate(con, project["id"], candidate["id"])
            promoted = promote_candidate(con, project["id"], candidate["id"])
            rejected = upsert_candidate(con, project["id"], "rule_candidate", "future", "Future rule", "Maybe later", confidence=5)
            rejected = reject_candidate(con, project["id"], rejected["id"], reason="not relevant")
            decision = get_decision(con, project["id"], "use-tool")
            con.close()
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(promoted["candidate"]["status"], "promoted")
            self.assertEqual(rejected["status"], "rejected")
            self.assertIsNotNone(decision)

    def test_candidate_dedup_by_key_and_promote_to_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project = self.make_db(tmp)
            first = upsert_candidate(
                con,
                project["id"],
                "failed_attempt",
                "cmd",
                "Repeated command",
                "Command failed twice.",
                proposed_target="brain_attempts",
                evidence={"command_preview": "python3 scripts/db.py stats"},
                confidence=6,
            )
            second = upsert_candidate(
                con,
                project["id"],
                "failed_attempt",
                "cmd",
                "Repeated command",
                "Command failed twice.",
                proposed_target="brain_attempts",
                evidence={"signals": ["repeated_failed_command"]},
                confidence=7,
            )
            promoted = promote_candidate(con, project["id"], second["id"])
            attempts = list_attempts(con, project["id"])
            con.close()
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(promoted["promoted"]["type"], "brain_attempts")
            self.assertEqual(len(attempts), 1)


if __name__ == "__main__":
    unittest.main()

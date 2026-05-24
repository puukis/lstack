import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.redaction import redact_text
from brain.capture import record_event
from brain.db import connect, ensure_project
from brain.decisions import add_decision, check_decisions
import tempfile


class TestBrainRedaction(unittest.TestCase):
    def assert_redacted(self, value):
        text, status = redact_text(value)
        self.assertEqual(status, "redacted")
        self.assertIn("<redacted>", text)

    def test_authorization_header(self):
        self.assert_redacted("Authorization: Bearer abc.def.ghi")

    def test_github_token(self):
        self.assert_redacted("GITHUB_TOKEN=ghp_fakefakefake")

    def test_npm_token(self):
        self.assert_redacted("NPM_TOKEN=npm_fakefakefake")

    def test_jwt(self):
        self.assert_redacted("eyJabcdefghi.eyJklmnopqr.abcdefghi123")

    def test_password_assignment(self):
        self.assert_redacted("password=supersecret")

    def test_pem_block(self):
        self.assert_redacted(
            "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----"
        )

    def test_env_style_api_key(self):
        self.assert_redacted("API_KEY=abc123")

    def test_clean_text(self):
        text, status = redact_text("normal output")
        self.assertEqual(status, "clean")
        self.assertEqual(text, "normal output")

    def test_decision_and_candidate_redact_fake_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            decision = add_decision(
                con,
                project["id"],
                key="secret",
                title="Secret",
                decision="Never store GITHUB_TOKEN=ghp_fakefakefake",
                evidence={"token": "npm_fakefakefake"},
                confidence=8,
            )
            result = record_event(
                con,
                project["id"],
                "user_correction",
                "do not use normal python again API_KEY=abc123",
                source="user",
            )
            con.close()
            self.assertEqual(decision["redaction_status"], "redacted")
            self.assertIn("<redacted>", decision["decision"])
            self.assertEqual(result["candidate"]["redaction_status"], "suspect")
            self.assertNotIn("abc123", str(result["candidate"]))

    def test_decision_check_redacts_matched_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / "bad.sh").write_text(
                "python3 run.py API_KEY=abc123\n",
                encoding="utf-8",
            )
            con = connect(root / "lstack.db")
            project = ensure_project(con, root)
            add_decision(
                con,
                project["id"],
                key="runtime",
                title="Runtime",
                decision="Use helper.",
                forbidden_patterns=["python3 "],
                applies_to=["scripts/*.sh"],
                confidence=8,
            )
            result = check_decisions(con, project)
            con.close()
            self.assertIn("<redacted>", result["violations"][0]["line_redacted"])
            self.assertNotIn("abc123", result["violations"][0]["line_redacted"])


if __name__ == "__main__":
    unittest.main()

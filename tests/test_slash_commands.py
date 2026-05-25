"""Validation tests for /receipt, /passport, and /work slash command skill files."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

RECEIPT_SKILL = SKILLS / "receipt" / "SKILL.md"
PASSPORT_SKILL = SKILLS / "passport" / "SKILL.md"
WORK_SKILL = SKILLS / "work" / "SKILL.md"

ALL_SKILLS = [RECEIPT_SKILL, PASSPORT_SKILL, WORK_SKILL]

# Patterns that must never appear in any command skill file
FORBIDDEN_PATTERNS = [
    (r"claude -p", "must not call claude -p"),
    (r"git reset", "must not run git reset"),
    (r"git clean", "must not run git clean"),
    (r"git restore", "must not run git restore"),
    (r"git push", "must not run git push"),
    (r"git pull", "must not run git pull"),
    (r"git commit", "must not run git commit"),
    (r"Phase 1[ABCD]", "must not mention roadmap phase labels"),
    (r"Phase 2[ABCD]", "must not mention roadmap phase labels"),
    (r"/c/Users/Leo", "must not contain hardcoded user path"),
    (r"C:\\\\Users\\\\Leo", "must not contain hardcoded Windows user path"),
    (r"leonard\.gunder", "must not contain hardcoded email"),
]


class TestSkillFilesExist(unittest.TestCase):
    def test_receipt_skill_exists(self):
        self.assertTrue(RECEIPT_SKILL.exists(), f"Missing: {RECEIPT_SKILL}")

    def test_passport_skill_exists(self):
        self.assertTrue(PASSPORT_SKILL.exists(), f"Missing: {PASSPORT_SKILL}")

    def test_work_skill_exists(self):
        self.assertTrue(WORK_SKILL.exists(), f"Missing: {WORK_SKILL}")


class TestSkillFrontmatter(unittest.TestCase):
    def _check_frontmatter(self, path, expected_name):
        text = path.read_text(encoding="utf-8")
        self.assertIn("---", text, f"{path.name}: missing YAML frontmatter")
        self.assertIn(f"name: {expected_name}", text, f"{path.name}: wrong or missing name field")
        self.assertIn("allowed-tools:", text, f"{path.name}: missing allowed-tools")
        self.assertIn("disable-model-invocation:", text, f"{path.name}: missing disable-model-invocation")

    def test_receipt_frontmatter(self):
        self._check_frontmatter(RECEIPT_SKILL, "receipt")

    def test_passport_frontmatter(self):
        self._check_frontmatter(PASSPORT_SKILL, "passport")

    def test_work_frontmatter(self):
        self._check_frontmatter(WORK_SKILL, "work")


class TestForbiddenPatterns(unittest.TestCase):
    def _check_file(self, path):
        text = path.read_text(encoding="utf-8")
        for pattern, reason in FORBIDDEN_PATTERNS:
            with self.subTest(file=path.name, pattern=pattern):
                self.assertIsNone(
                    re.search(pattern, text),
                    f"{path.name}: {reason} (found: {pattern!r})",
                )

    def test_receipt_no_forbidden(self):
        self._check_file(RECEIPT_SKILL)

    def test_passport_no_forbidden(self):
        self._check_file(PASSPORT_SKILL)

    def test_work_no_forbidden(self):
        self._check_file(WORK_SKILL)


class TestReceiptCLIReferences(unittest.TestCase):
    def setUp(self):
        self.text = RECEIPT_SKILL.read_text(encoding="utf-8")

    def test_references_receipt_start(self):
        self.assertIn("lstack brain receipt start", self.text)

    def test_references_receipt_status(self):
        self.assertIn("lstack brain receipt status", self.text)

    def test_references_receipt_finalize(self):
        self.assertIn("lstack brain receipt finalize", self.text)

    def test_references_receipt_abandon(self):
        self.assertIn("lstack brain receipt abandon", self.text)

    def test_references_receipt_list(self):
        self.assertIn("lstack brain receipt list", self.text)

    def test_references_receipt_explain(self):
        self.assertIn("lstack brain receipt explain", self.text)

    def test_references_receipt_undo_hint(self):
        self.assertIn("lstack brain receipt undo-hint", self.text)

    def test_references_receipt_record_test(self):
        self.assertIn("lstack brain receipt record-test", self.text)

    def test_references_receipt_record_command(self):
        self.assertIn("lstack brain receipt record-command", self.text)

    def test_abandon_uses_required_reason_flag(self):
        # --reason is required by CLI; skill must supply it
        self.assertIn("--reason", self.text)

    def test_show_uses_positional_id(self):
        # show takes a positional int, not --id
        self.assertIn("receipt show <id>", self.text)


class TestPassportCLIReferences(unittest.TestCase):
    def setUp(self):
        self.text = PASSPORT_SKILL.read_text(encoding="utf-8")

    def test_references_passport(self):
        self.assertIn("lstack brain passport", self.text)

    def test_references_context_for_claude(self):
        self.assertIn("lstack brain context --for claude", self.text)

    def test_references_overview(self):
        self.assertIn("lstack brain overview", self.text)

    def test_references_doctor(self):
        self.assertIn("lstack brain doctor", self.text)

    def test_references_passport_refresh(self):
        self.assertIn("passport refresh", self.text)


class TestWorkCLIReferences(unittest.TestCase):
    def setUp(self):
        self.text = WORK_SKILL.read_text(encoding="utf-8")

    def test_references_overview(self):
        self.assertIn("lstack brain overview", self.text)

    def test_references_context_for_claude(self):
        self.assertIn("lstack brain context --for claude", self.text)

    def test_references_receipt_status(self):
        self.assertIn("lstack brain receipt status", self.text)

    def test_references_receipt_start(self):
        self.assertIn("lstack brain receipt start", self.text)

    def test_references_firewall_status(self):
        self.assertIn("lstack brain firewall status", self.text)

    def test_references_firewall_check(self):
        self.assertIn("lstack brain firewall check", self.text)


class TestDocsCLISourceOfTruth(unittest.TestCase):
    def test_lbrain_doc_mentions_cli_source_of_truth(self):
        doc = (ROOT / "docs" / "lbrain.md").read_text(encoding="utf-8")
        self.assertIn("source of truth", doc.lower())

    def test_lbrain_doc_mentions_slash_commands(self):
        doc = (ROOT / "docs" / "lbrain.md").read_text(encoding="utf-8")
        self.assertIn("/receipt", doc)
        self.assertIn("/passport", doc)
        self.assertIn("/work", doc)

    def test_readme_mentions_slash_commands(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("/receipt", readme)
        self.assertIn("/passport", readme)
        self.assertIn("/work", readme)


if __name__ == "__main__":
    unittest.main()

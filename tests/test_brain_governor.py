"""Tests for Context Governor."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.attempts import add_attempt
from brain.capture import upsert_candidate
from brain.context import build_context
from brain.db import connect, ensure_project
from brain.decisions import add_decision, disable_decision
from brain.governor import run_governor, governor_summary
from brain.passport import get_or_refresh_passport


def _make_project(tmp):
    root = Path(tmp)
    con = connect(root / "lstack.db")
    project = ensure_project(con, root)
    return con, project, root


class TestGovernorMandatory(unittest.TestCase):
    """Tests 1-3: mandatory items are always included."""

    def test_governor_includes_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            result = run_governor(con, project, target="claude")
            con.close()
            types = [it["item_type"] for it in result["included"]]
            self.assertIn("platform", types)

    def test_governor_includes_passport(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            result = run_governor(con, project, target="claude")
            con.close()
            types = [it["item_type"] for it in result["included"]]
            self.assertIn("passport", types)

    def test_governor_platform_mandatory_for_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            result = run_governor(con, project, target="claude")
            con.close()
            platform_items = [it for it in result["items"] if it["item_type"] == "platform"]
            self.assertTrue(platform_items)
            self.assertTrue(platform_items[0]["mandatory"])


class TestGovernorDecisions(unittest.TestCase):
    """Tests 4-5: decisions included/skipped correctly."""

    def test_governor_includes_active_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            add_decision(
                con, project["id"],
                key="test-governor-decision",
                title="Test Decision",
                decision="Use test approach.",
                confidence=9,
            )
            result = run_governor(con, project, target="claude")
            con.close()
            included_keys = [it.get("key") for it in result["included"]]
            self.assertIn("test-governor-decision", included_keys)

    def test_governor_skips_disabled_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            add_decision(
                con, project["id"],
                key="disabled-dec",
                title="To Disable",
                decision="Will be disabled.",
                confidence=9,
            )
            disable_decision(con, project["id"], "disabled-dec")
            result = run_governor(con, project, target="claude")
            con.close()
            included_keys = [it.get("key") for it in result["included"]]
            self.assertNotIn("disabled-dec", included_keys)


class TestGovernorAttempts(unittest.TestCase):
    """Tests 6-7: high-confidence attempts included, low-confidence skipped."""

    def test_governor_includes_high_confidence_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            add_attempt(
                con, project["id"],
                "Tried npm install",
                why_failed="Repo uses pnpm",
                retry_policy="never",
                confidence=9,
            )
            result = run_governor(con, project, target="claude")
            con.close()
            types = [it["item_type"] for it in result["included"]]
            self.assertIn("attempt", types)

    def test_governor_skips_low_confidence_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            add_attempt(
                con, project["id"],
                "Low confidence action",
                why_failed="Not sure why",
                retry_policy="ask",
                confidence=4,
            )
            result = run_governor(con, project, target="claude")
            con.close()
            included_attempts = [it for it in result["included"] if it["item_type"] == "attempt"]
            self.assertEqual(included_attempts, [])


class TestGovernorPendingCandidates(unittest.TestCase):
    """Tests 8-9: pending candidates excluded from normal, shown in debug."""

    def test_governor_skips_pending_candidates_in_normal(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            upsert_candidate(
                con, project["id"],
                "implementation_decision", "maybe-key", "Maybe title",
                "Pending candidate content.", confidence=6,
            )
            result = run_governor(con, project, target="claude")
            con.close()
            types = [it["item_type"] for it in result["included"]]
            self.assertNotIn("candidate", types)

    def test_governor_shows_pending_candidates_in_debug(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            upsert_candidate(
                con, project["id"],
                "implementation_decision", "maybe-key2", "Maybe title 2",
                "Pending candidate content.", confidence=6,
            )
            result = run_governor(con, project, target="claude", debug=True)
            con.close()
            skipped_types = [it["item_type"] for it in result["skipped"]]
            self.assertIn("candidate", skipped_types)


class TestGovernorBudget(unittest.TestCase):
    """Test 10: budget is tracked."""

    def test_governor_tracks_estimated_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            result = run_governor(con, project, target="claude", budget=6000)
            con.close()
            self.assertIn("estimated_tokens", result)
            self.assertGreater(result["estimated_tokens"], 0)
            self.assertEqual(result["budget"], 6000)

    def test_governor_summary_has_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            result = run_governor(con, project, target="claude")
            summary = governor_summary(result)
            con.close()
            self.assertIn("included_count", summary)
            self.assertIn("skipped_count", summary)
            self.assertIn("estimated_tokens", summary)
            self.assertGreater(summary["included_count"], 0)


class TestGovernorRedaction(unittest.TestCase):
    """Test 11: redaction."""

    def test_governor_redacts_unsafe_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            add_decision(
                con, project["id"],
                key="secret-dec",
                title="Secret",
                decision="Do not use GITHUB_TOKEN=ghp_fakefakefake in examples.",
                confidence=8,
            )
            result = run_governor(con, project, target="claude")
            con.close()
            all_texts = " ".join(it["text"] for it in result["included"])
            self.assertNotIn("ghp_fakefakefake", all_texts)
            self.assertIn("<redacted>", all_texts)


class TestGovernorContextCompat(unittest.TestCase):
    """Tests 12-13: context output compatibility."""

    def test_context_for_claude_text_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, root = _make_project(tmp)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "pytest"}, "packageManager": "npm@9.0.0"}),
                encoding="utf-8",
            )
            get_or_refresh_passport(con, project, refresh=True)
            text = build_context(con, project, target="claude")
            con.close()
            self.assertIn("Platform:", text)
            self.assertIn("LBrain context for Claude", text)

    def test_context_json_includes_governor_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            data = build_context(con, project, target="claude", json_mode=True)
            con.close()
            self.assertIn("governor", data)
            gov = data["governor"]
            self.assertIn("included_count", gov)
            self.assertIn("skipped_count", gov)
            self.assertIn("target", gov)
            self.assertEqual(gov["target"], "claude")

    def test_context_json_no_phase_names(self):
        import re
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            data = build_context(con, project, target="claude", json_mode=True)
            con.close()
            text = json.dumps(data)
            forbidden = re.compile(
                r"Phase\s+1[ABCD]|phase\s+1[abcd]|phase1[abcd]",
                re.IGNORECASE,
            )
            self.assertIsNone(forbidden.search(text), "Phase label found in context JSON output")


class TestGovernorItemModel(unittest.TestCase):
    """Governor items have full model fields."""

    def test_governor_items_have_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            result = run_governor(con, project, target="claude")
            con.close()
            required = {
                "item_type", "text", "source_feature", "priority",
                "confidence", "relevance_score", "mandatory",
                "included", "reason", "redaction_status",
            }
            for item in result["items"]:
                missing = required - set(item.keys())
                self.assertEqual(missing, set(), f"Item {item['item_type']} missing fields: {missing}")

    def test_governor_has_decision_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            con, project, _ = _make_project(tmp)
            result = run_governor(con, project, target="claude")
            con.close()
            self.assertIn("decision_log", result)
            self.assertTrue(len(result["decision_log"]) > 0)
            for entry in result["decision_log"]:
                self.assertEqual(len(entry), 7)


if __name__ == "__main__":
    unittest.main()

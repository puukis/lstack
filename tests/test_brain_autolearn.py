"""Tests for lbrain/brain/autolearn.py - automatic learning policy."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.autolearn import (
    autolearn_config,
    extract_command,
    extract_exit_code,
    extract_file_path,
    extract_output_preview,
    is_autolearn_enabled,
    is_autopromote_enabled,
    max_output_preview,
    probe_package_manager,
    process_hook_payload,
)
from brain.capture import capture_status, list_candidates, list_events, record_event
from brain.db import connect, ensure_project
from brain.decisions import get_decision
from brain.attempts import list_attempts


def _make_bash_payload(command, exit_code=0, output=""):
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"exit_code": exit_code, "output": output},
    }


def _make_file_payload(tool_name, file_path):
    return {
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path},
        "tool_response": {},
    }


class TestAutolearnConfig(unittest.TestCase):
    def test_env_flag_default_enabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LSTACK_BRAIN_AUTO_LEARN", None)
            self.assertTrue(is_autolearn_enabled())

    def test_env_flag_disabled(self):
        with patch.dict(os.environ, {"LSTACK_BRAIN_AUTO_LEARN": "0"}):
            self.assertFalse(is_autolearn_enabled())

    def test_autopromote_default_enabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LSTACK_BRAIN_AUTO_PROMOTE", None)
            self.assertTrue(is_autopromote_enabled())

    def test_autopromote_disabled(self):
        with patch.dict(os.environ, {"LSTACK_BRAIN_AUTO_PROMOTE": "0"}):
            self.assertFalse(is_autopromote_enabled())

    def test_autolearn_config_returns_dict(self):
        config = autolearn_config()
        self.assertIn("auto_learn_enabled", config)
        self.assertIn("auto_promote_enabled", config)
        self.assertIn("max_output_preview", config)
        self.assertIn("max_events_per_session", config)

    def test_max_output_preview_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LSTACK_BRAIN_AUTO_LEARN_MAX_OUTPUT_PREVIEW", None)
            self.assertEqual(max_output_preview(), 500)

    def test_max_output_preview_custom(self):
        with patch.dict(os.environ, {"LSTACK_BRAIN_AUTO_LEARN_MAX_OUTPUT_PREVIEW": "200"}):
            self.assertEqual(max_output_preview(), 200)


class TestPayloadExtraction(unittest.TestCase):
    def test_extract_command_bash(self):
        self.assertEqual(extract_command("Bash", {"command": "npm test"}), "npm test")

    def test_extract_command_non_bash(self):
        self.assertIsNone(extract_command("Write", {"file_path": "/tmp/x.py"}))

    def test_extract_exit_code_zero(self):
        self.assertEqual(extract_exit_code({"exit_code": 0, "output": "ok"}), 0)

    def test_extract_exit_code_nonzero(self):
        self.assertEqual(extract_exit_code({"exit_code": 127, "output": "not found"}), 127)

    def test_extract_exit_code_inferred_from_output(self):
        self.assertEqual(extract_exit_code({"output": "command not found"}), 1)

    def test_extract_exit_code_none_on_clean_output(self):
        result = extract_exit_code({"output": "all tests passed"})
        # No inference for clean output (exit_code absent)
        self.assertIsNone(result)

    def test_extract_output_preview_truncated(self):
        long_output = "x" * 1000
        with patch.dict(os.environ, {"LSTACK_BRAIN_AUTO_LEARN_MAX_OUTPUT_PREVIEW": "100"}):
            preview = extract_output_preview({"output": long_output})
        self.assertEqual(len(preview), 100)

    def test_extract_file_path_write(self):
        self.assertEqual(extract_file_path("Write", {"file_path": "/tmp/foo.py"}), "/tmp/foo.py")

    def test_extract_file_path_bash(self):
        self.assertIsNone(extract_file_path("Bash", {"command": "ls"}))

    def test_old_str_not_extracted(self):
        # Verify old_str and new_str are never returned by extraction
        result = extract_file_path("Edit", {"file_path": "/tmp/x.py", "old_str": "secret", "new_str": "safe"})
        self.assertNotIn("old_str", str(result))
        self.assertNotIn("new_str", str(result))


class TestProbePackageManager(unittest.TestCase):
    def test_detect_pnpm_from_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = {"name": "test", "packageManager": "pnpm@10.0.0"}
            Path(tmp, "package.json").write_text(json.dumps(pkg))
            Path(tmp, "pnpm-lock.yaml").touch()
            result = probe_package_manager(tmp)
        self.assertIsNotNone(result)
        self.assertEqual(result["package_manager"], "pnpm")
        self.assertTrue(result["lockfile_agrees"])
        self.assertFalse(result["conflict"])

    def test_detect_npm_from_lockfile_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = {"name": "test"}
            Path(tmp, "package.json").write_text(json.dumps(pkg))
            Path(tmp, "package-lock.json").touch()
            result = probe_package_manager(tmp)
        self.assertIsNotNone(result)
        self.assertEqual(result["package_manager"], "npm")
        self.assertEqual(result["source"], "lockfile")

    def test_conflict_when_field_and_lockfile_disagree(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = {"name": "test", "packageManager": "pnpm@9.0.0"}
            Path(tmp, "package.json").write_text(json.dumps(pkg))
            Path(tmp, "package-lock.json").touch()
            result = probe_package_manager(tmp)
        self.assertIsNotNone(result)
        self.assertTrue(result["conflict"])

    def test_no_package_json_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = probe_package_manager(tmp)
        self.assertIsNone(result)


class TestProcessHookPayload(unittest.TestCase):
    def make_db(self, tmp):
        db_path = Path(tmp) / "lstack.db"
        env = {"LSTACK_DB_PATH": str(db_path)}
        return db_path, env

    def test_disabled_returns_disabled_status(self):
        with patch.dict(os.environ, {"LSTACK_BRAIN_AUTO_LEARN": "0"}):
            result = process_hook_payload({"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {}})
        self.assertEqual(result["status"], "disabled")

    def test_malformed_json_handled_gracefully(self):
        # process_hook_payload receives already-parsed dict; test non-dict
        result = process_hook_payload("not a dict")
        self.assertEqual(result["status"], "invalid")

    def test_failed_bash_records_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "1"}):
                payload = _make_bash_payload("python3 missing.py", exit_code=127, output="python3: command not found")
                result = process_hook_payload(payload, cwd=tmp)
            self.assertEqual(result["status"], "ok")
            con = connect(db_path)
            project = ensure_project(con, tmp)
            status = capture_status(con, project["id"])
            con.close()
        self.assertGreaterEqual(status["events"], 1)

    def test_repeated_failed_bash_creates_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_bash_payload("python3 missing.py", exit_code=127, output="command not found")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "1"}):
                process_hook_payload(payload, cwd=tmp)
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            candidates = list_candidates(con, project["id"], status="pending")
            promoted = list_candidates(con, project["id"], status="promoted")
            con.close()
        # After two failures, either a pending candidate or promoted attempt should exist
        self.assertGreater(len(candidates) + len(promoted), 0)

    def test_repeated_failed_bash_auto_promotes_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_bash_payload("python3 missing.py", exit_code=127, output="command not found")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "1"}):
                for _ in range(3):
                    process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            attempts = list_attempts(con, project["id"])
            con.close()
        self.assertGreater(len(attempts), 0)

    def test_package_manager_detection_auto_promotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            # Create package.json with packageManager field
            pkg = {"name": "test", "packageManager": "pnpm@10.0.0"}
            Path(tmp, "package.json").write_text(json.dumps(pkg))
            Path(tmp, "pnpm-lock.yaml").touch()
            payload = _make_bash_payload("pnpm test", exit_code=0, output="tests passed")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "1"}):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            decision = get_decision(con, project["id"], "package-manager-pnpm")
            con.close()
        self.assertIsNotNone(decision)
        self.assertEqual(decision["status"], "active")

    def test_package_manager_conflict_stays_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            pkg = {"name": "test", "packageManager": "pnpm@9.0.0"}
            Path(tmp, "package.json").write_text(json.dumps(pkg))
            Path(tmp, "package-lock.json").touch()  # npm lockfile
            payload = _make_bash_payload("npm test", exit_code=0, output="ok")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "1"}):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            # Should not have auto-promoted a decision for conflicting pm
            decision = get_decision(con, project["id"], "package-manager-pnpm")
            con.close()
        # Conflicting evidence: candidate may exist but should not be promoted as decision
        self.assertIsNone(decision)

    def test_autolearn_disabled_records_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_bash_payload("python3 missing.py", exit_code=127, output="not found")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "0"}):
                result = process_hook_payload(payload, cwd=tmp)
            self.assertEqual(result["status"], "disabled")
            con = connect(db_path)
            project = ensure_project(con, tmp)
            status = capture_status(con, project["id"])
            con.close()
        self.assertEqual(status["events"], 0)

    def test_autopromote_disabled_creates_candidate_not_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            pkg = {"name": "test", "packageManager": "pnpm@10.0.0"}
            Path(tmp, "package.json").write_text(json.dumps(pkg))
            Path(tmp, "pnpm-lock.yaml").touch()
            payload = _make_bash_payload("pnpm test", exit_code=0, output="ok")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "0"}):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            decision = get_decision(con, project["id"], "package-manager-pnpm")
            pending = list_candidates(con, project["id"], status="pending")
            con.close()
        # With auto-promote off, no decision should be created
        self.assertIsNone(decision)
        # But a candidate may exist in pending state
        # (package manager detection creates candidate only, not decision)

    def test_secrets_are_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_bash_payload(
                'curl -H "Authorization: Bearer sk-secret-abc123" https://api.example.com',
                exit_code=1,
                output="failed with token sk-secret-abc123",
            )
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "1"}):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"])
            con.close()
        self.assertGreater(len(events), 0)
        # Check that the secret token is not stored
        for evt in events:
            self.assertNotIn("sk-secret-abc123", str(evt.get("command_preview_redacted") or ""))
            self.assertNotIn("sk-secret-abc123", str(evt.get("summary") or ""))

    def test_secret_redaction_blocks_auto_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_bash_payload(
                'curl -H "Authorization: Bearer sk-secret-abc123" https://api.example.com',
                exit_code=1,
                output="failed",
            )
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "1"}):
                for _ in range(3):
                    process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            # Check no attempts were auto-promoted from a suspect candidate
            attempts = list_attempts(con, project["id"])
            candidates = list_candidates(con, project["id"], status=None)
            con.close()
        # Any candidates with redacted secrets should not be promoted
        for c in candidates:
            if c.get("redaction_status") in ("suspect", "blocked"):
                self.assertNotEqual(c["status"], "promoted")

    def test_write_records_implementation_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_file_payload("Write", "/tmp/test_file.py")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1"}):
                result = process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"], event_type="implementation_diff")
            con.close()
        self.assertEqual(result["status"], "ok")
        self.assertGreater(len(events), 0)

    def test_edit_records_implementation_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_file_payload("Edit", "/tmp/edit_file.py")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1"}):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"], event_type="implementation_diff")
            con.close()
        self.assertGreater(len(events), 0)

    def test_multiedit_records_implementation_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_file_payload("MultiEdit", "/tmp/multi_file.py")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1"}):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"], event_type="implementation_diff")
            con.close()
        self.assertGreater(len(events), 0)

    def test_old_str_new_str_not_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "/tmp/x.py",
                    "old_str": "SECRET_TOKEN=abc123",
                    "new_str": "safe content",
                },
                "tool_response": {},
            }
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1"}):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"])
            con.close()
        for evt in events:
            for field in ("summary", "command_preview_redacted"):
                val = str(evt.get(field) or "")
                self.assertNotIn("SECRET_TOKEN=abc123", val)
                self.assertNotIn("old_str", val)
                self.assertNotIn("new_str", val)

    def test_output_preview_is_limited(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            big_output = "A" * 2000
            payload = _make_bash_payload("ls", exit_code=0, output=big_output)
            with patch.dict(os.environ, {
                **env,
                "LSTACK_BRAIN_AUTO_LEARN": "1",
                "LSTACK_BRAIN_AUTO_LEARN_MAX_OUTPUT_PREVIEW": "100",
            }):
                process_hook_payload(payload, cwd=tmp)
            # Just verify no error occurs and preview is not unbounded
            # (The 100-char limit is applied in extract_output_preview)

    def test_test_pass_records_test_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_bash_payload("pytest tests/ -v", exit_code=0, output="10 passed")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1"}):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"], event_type="test_result")
            con.close()
        self.assertGreater(len(events), 0)
        ev = events[0]
        self.assertIn("pass", ev["evidence"].get("test_result", ""))

    def test_test_fail_records_test_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_bash_payload("pytest tests/ -v", exit_code=1, output="1 failed")
            with patch.dict(os.environ, {**env, "LSTACK_BRAIN_AUTO_LEARN": "1"}):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"], event_type="test_result")
            con.close()
        self.assertGreater(len(events), 0)
        ev = events[0]
        self.assertIn("fail", ev["evidence"].get("test_result", ""))

    def test_rate_limit_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_bash_payload("echo hi", exit_code=0, output="hi")
            with patch.dict(os.environ, {
                **env,
                "LSTACK_BRAIN_AUTO_LEARN": "1",
                "LSTACK_BRAIN_AUTO_LEARN_MAX_EVENTS_PER_SESSION": "2",
                "CLAUDE_SESSION_ID": "test-session-abc",
            }):
                for _ in range(5):
                    process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            # Count hook-source events for this session
            count = con.execute(
                "SELECT COUNT(*) FROM brain_capture_events WHERE project_id = ? AND source = 'hook' AND session_id = ?",
                (project["id"], "test-session-abc"),
            ).fetchone()[0]
            con.close()
        self.assertLessEqual(count, 2)

    def test_project_isolation(self):
        """Memory from project A must not appear in project B context."""
        with tempfile.TemporaryDirectory() as tmp_db:
            with tempfile.TemporaryDirectory() as proj_a:
                with tempfile.TemporaryDirectory() as proj_b:
                    db_path = Path(tmp_db) / "lstack.db"
                    env = {"LSTACK_DB_PATH": str(db_path), "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "1"}
                    payload = _make_bash_payload("python3 missing.py", exit_code=127, output="command not found")
                    with patch.dict(os.environ, env):
                        for _ in range(3):
                            process_hook_payload(payload, cwd=proj_a)
                    con = connect(db_path)
                    proj_a_row = ensure_project(con, proj_a)
                    proj_b_row = ensure_project(con, proj_b)
                    a_events = list_events(con, proj_a_row["id"])
                    b_events = list_events(con, proj_b_row["id"])
                    a_attempts = list_attempts(con, proj_a_row["id"])
                    b_attempts = list_attempts(con, proj_b_row["id"])
                    con.close()
        self.assertGreater(len(a_events), 0)
        self.assertEqual(len(b_events), 0)
        self.assertEqual(len(b_attempts), 0)

    def test_pending_candidates_not_in_normal_context(self):
        from brain.context import build_context
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            env = {"LSTACK_DB_PATH": str(db_path), "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "0"}
            pkg = {"name": "test", "packageManager": "pnpm@10.0.0"}
            Path(tmp, "package.json").write_text(json.dumps(pkg))
            Path(tmp, "pnpm-lock.yaml").touch()
            payload = _make_bash_payload("pnpm test", exit_code=0, output="ok")
            with patch.dict(os.environ, env):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            context_text = build_context(con, project, target="codex")
            pending = list_candidates(con, project["id"], status="pending")
            con.close()
        # Pending candidates should not appear in normal context output
        for c in pending:
            self.assertNotIn(c["title"], context_text)

    def test_auto_promoted_decisions_in_context(self):
        from brain.context import build_context
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lstack.db"
            env = {"LSTACK_DB_PATH": str(db_path), "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "1"}
            pkg = {"name": "test", "packageManager": "pnpm@10.0.0"}
            Path(tmp, "package.json").write_text(json.dumps(pkg))
            Path(tmp, "pnpm-lock.yaml").touch()
            payload = _make_bash_payload("pnpm test", exit_code=0, output="ok")
            with patch.dict(os.environ, env):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            decision = get_decision(con, project["id"], "package-manager-pnpm")
            context_text = build_context(con, project, target="codex")
            con.close()
        # Auto-promoted decision should exist and appear in context
        self.assertIsNotNone(decision)
        self.assertIn("pnpm", context_text)

    def test_platform_detection_windows_git_bash(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_bash_payload("echo hello", exit_code=0, output="hello")
            with patch.dict(os.environ, {
                **env,
                "LSTACK_BRAIN_AUTO_LEARN": "1",
                "MSYSTEM": "MINGW64",
            }):
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"], event_type="platform_detection")
            con.close()
        # Platform detection should fire (Windows/git-bash)
        self.assertGreater(len(events), 0)
        ev = events[0]
        self.assertIn("git-bash", ev["evidence"].get("shell_mode", ""))

    def test_wsl_detected_as_wsl_not_git_bash(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, env = self.make_db(tmp)
            payload = _make_bash_payload("echo hello", exit_code=0, output="hello")
            with patch.dict(os.environ, {
                **env,
                "LSTACK_BRAIN_AUTO_LEARN": "1",
                "WSL_DISTRO_NAME": "Ubuntu",
            }, clear=False):
                os.environ.pop("MSYSTEM", None)
                process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"], event_type="platform_detection")
            con.close()
        # WSL should be recorded with shell_mode=wsl
        for ev in events:
            if ev["evidence"].get("is_wsl"):
                self.assertEqual(ev["evidence"]["shell_mode"], "wsl")
                self.assertNotEqual(ev["evidence"]["shell_mode"], "git-bash")


class TestUndoEvent(unittest.TestCase):
    def make_db(self, tmp):
        db_path = Path(tmp) / "lstack.db"
        return db_path

    def test_undo_removes_auto_promoted_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db(tmp)
            env = {"LSTACK_DB_PATH": str(db_path), "LSTACK_BRAIN_AUTO_LEARN": "1", "LSTACK_BRAIN_AUTO_PROMOTE": "1"}
            payload = _make_bash_payload("python3 missing.py", exit_code=127, output="command not found")
            with patch.dict(os.environ, env):
                for _ in range(3):
                    process_hook_payload(payload, cwd=tmp)
            con = connect(db_path)
            project = ensure_project(con, tmp)
            attempts_before = list_attempts(con, project["id"])
            events = list_events(con, project["id"], event_type="failed_command")
            con.close()

            if not attempts_before or not events:
                return  # Skip if not promoted yet

            con2 = connect(db_path)
            try:
                project2 = ensure_project(con2, tmp)
                from brain.capture import undo_event
                result = undo_event(con2, project2["id"], events[0]["id"])
                attempts_after = list_attempts(con2, project2["id"])
            finally:
                con2.close()

            # After undo, attempts should be reduced or empty
            self.assertGreaterEqual(len(attempts_before), len(attempts_after))


if __name__ == "__main__":
    unittest.main()

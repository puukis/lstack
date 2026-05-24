"""Runtime tests for hooks/post-tool.sh executed via bash.

These tests complement bash -n syntax checks by actually running the hook
and asserting runtime behavior: exit codes, stderr cleanliness, capture
recording, auto-promotion, and formatter branch safety.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "post-tool.sh"
LBRAIN = ROOT / "lbrain"

sys.path.insert(0, str(LBRAIN))


def _find_bash():
    for candidate in [
        "bash",
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]:
        found = shutil.which(candidate)
        if found:
            return found
        if os.path.isfile(candidate):
            return candidate
    return None


BASH = _find_bash()


def _run_hook(payload_dict, env_extra=None, cwd=None):
    env = os.environ.copy()
    env["LSTACK_BRAIN_AUTO_LEARN"] = "1"
    env["LSTACK_BRAIN_AUTO_PROMOTE"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [BASH, str(HOOK)],
        input=json.dumps(payload_dict),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd or tempfile.gettempdir(),
        timeout=30,
    )


def _bash_payload(command, exit_code=0, output=""):
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"exit_code": exit_code, "output": output},
    }


def _edit_payload(file_path, old_str="a", new_str="b"):
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path, "old_string": old_str, "new_string": new_str},
        "tool_response": {},
    }


@unittest.skipIf(BASH is None, "bash not available")
class TestPostToolShRuntime(unittest.TestCase):

    def test_bash_failed_command_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lstack.db"
            r = _run_hook(
                _bash_payload("python3 missing.py", exit_code=127, output="command not found"),
                env_extra={"LSTACK_DB_PATH": str(db)},
                cwd=tmp,
            )
        self.assertEqual(r.returncode, 0)

    def test_bash_failed_command_no_syntax_error_in_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lstack.db"
            r = _run_hook(
                _bash_payload("python3 missing.py", exit_code=127, output="command not found"),
                env_extra={"LSTACK_DB_PATH": str(db)},
                cwd=tmp,
            )
        self.assertNotIn("syntax error", r.stderr)

    def test_bash_failed_command_records_capture_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lstack.db"
            r = _run_hook(
                _bash_payload("python3 missing.py", exit_code=127, output="command not found"),
                env_extra={"LSTACK_DB_PATH": str(db)},
                cwd=tmp,
            )
            self.assertEqual(r.returncode, 0)
            from brain.db import connect, ensure_project
            from brain.capture import list_events
            con = connect(db)
            project = ensure_project(con, tmp)
            events = list_events(con, project["id"])
            con.close()
        self.assertGreater(len(events), 0)

    def test_bash_repeated_failure_auto_promotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lstack.db"
            payload = _bash_payload("python3 missing.py", exit_code=127, output="command not found")
            for _ in range(3):
                r = _run_hook(payload, env_extra={"LSTACK_DB_PATH": str(db)}, cwd=tmp)
                self.assertEqual(r.returncode, 0)
                self.assertNotIn("syntax error", r.stderr)

            from brain.db import connect, ensure_project
            from brain.capture import list_candidates
            con = connect(db)
            project = ensure_project(con, tmp)
            candidates = list_candidates(con, project["id"], status=None)
            con.close()

        promoted = [c for c in candidates if c["status"] == "promoted"]
        self.assertGreater(len(promoted), 0, f"Expected at least one promoted candidate, got: {candidates}")

    def test_bash_large_output_emits_warning(self):
        large_output = "x" * 4000
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lstack.db"
            r = _run_hook(
                _bash_payload("cat bigfile.txt", exit_code=0, output=large_output),
                env_extra={"LSTACK_DB_PATH": str(db)},
                cwd=tmp,
            )
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("syntax error", r.stderr)
        self.assertIn("Large tool response", r.stdout)
        self.assertIn("4000", r.stdout)

    def test_bash_small_output_no_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lstack.db"
            r = _run_hook(
                _bash_payload("echo hi", exit_code=0, output="hi"),
                env_extra={"LSTACK_DB_PATH": str(db)},
                cwd=tmp,
            )
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Large tool response", r.stdout)

    def test_edit_payload_with_existing_file_no_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "sample.txt"
            f.write_text("hello world\n")
            db = Path(tmp) / "lstack.db"
            r = _run_hook(
                _edit_payload(str(f)),
                env_extra={"LSTACK_DB_PATH": str(db)},
                cwd=tmp,
            )
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("syntax error", r.stderr)

    def test_edit_payload_no_file_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run_hook(
                _edit_payload("/nonexistent/path/file.py"),
                cwd=tmp,
            )
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("syntax error", r.stderr)

    def test_malformed_json_exits_zero(self):
        env = os.environ.copy()
        r = subprocess.run(
            [BASH, str(HOOK)],
            input="{not valid json",
            capture_output=True,
            text=True,
            env=env,
            cwd=tempfile.gettempdir(),
            timeout=15,
        )
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("syntax error", r.stderr)

    def test_empty_stdin_exits_zero(self):
        env = os.environ.copy()
        r = subprocess.run(
            [BASH, str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            env=env,
            cwd=tempfile.gettempdir(),
            timeout=15,
        )
        self.assertEqual(r.returncode, 0)

    def test_no_claude_p_in_hook(self):
        import re
        content = HOOK.read_text(encoding="utf-8", errors="ignore")
        pattern = re.compile(r"\bclaude\s+-p\b")
        violations = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if pattern.search(line):
                violations.append(f"{i}: {stripped}")
        self.assertEqual(violations, [], "Found active claude -p in hook:\n" + "\n".join(violations))

    def test_bash_n_passes(self):
        """bash -n syntax check must still pass after the fix."""
        r = subprocess.run(
            [BASH, "-n", str(HOOK)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(r.returncode, 0, f"bash -n failed:\n{r.stderr}")

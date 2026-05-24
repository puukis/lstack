import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lbrain"))

from brain.platform import normalize_path, path_warnings, platform_facts


class TestBrainCrossPlatform(unittest.TestCase):
    def test_windows_backslash_path(self):
        self.assertEqual(normalize_path(r"C:\Users\Name\repo"), "C:/Users/Name/repo")

    def test_windows_forward_path(self):
        self.assertEqual(normalize_path("C:/Users/Name/repo"), "C:/Users/Name/repo")

    def test_git_bash_c_path(self):
        self.assertEqual(normalize_path("/c/Users/Name/repo"), "C:/Users/Name/repo")

    def test_git_bash_d_path_with_spaces(self):
        self.assertEqual(normalize_path("/d/Work Space/repo"), "D:/Work Space/repo")

    def test_mnt_path_warning_in_git_bash(self):
        warnings = path_warnings("/mnt/c/Users/Name/repo", "git-bash")
        self.assertTrue(warnings)

    def test_macos_path(self):
        self.assertEqual(normalize_path("/Users/name/repo"), "/Users/name/repo")

    def test_linux_path(self):
        self.assertEqual(normalize_path("/home/name/repo"), "/home/name/repo")

    def test_windows_git_bash_mode(self):
        facts = platform_facts(
            env={"MSYSTEM": "MINGW64", "SHELL": "/usr/bin/bash"},
            system_name="Windows",
            proc_version="",
        )
        self.assertEqual(facts["os"], "windows")
        self.assertEqual(facts["shell_mode"], "git-bash")
        self.assertIn("/c/...", facts["path_style"])
        self.assertFalse(facts["is_wsl"])

    def test_wsl_mode_warns_but_stays_linux(self):
        facts = platform_facts(
            env={"WSL_DISTRO_NAME": "Ubuntu", "SHELL": "/bin/bash"},
            system_name="Linux",
            proc_version="Linux version with Microsoft",
        )
        self.assertEqual(facts["os"], "linux")
        self.assertEqual(facts["shell_mode"], "wsl")
        self.assertTrue(facts["is_wsl"])
        self.assertIn("Git Bash", facts["warnings"][0])

    def test_linux_mode_still_works(self):
        facts = platform_facts(
            env={"SHELL": "/bin/bash"},
            system_name="Linux",
            proc_version="Linux version generic",
        )
        self.assertEqual(facts["os"], "linux")
        self.assertEqual(facts["shell_mode"], "bash")
        self.assertFalse(facts["is_wsl"])
        self.assertEqual(facts["warnings"], [])


if __name__ == "__main__":
    unittest.main()

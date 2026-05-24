import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestBrainPackaging(unittest.TestCase):
    def test_lstack_routes_to_top_level_lbrain(self):
        content = (ROOT / "bin" / "lstack").read_text(encoding="utf-8")
        self.assertIn('${CLAUDE_DIR}/lbrain/brain.py', content)
        self.assertNotIn('${CLAUDE_DIR}/scripts/brain.py', content)

    def test_publish_includes_lbrain_sources(self):
        content = (ROOT / "bin" / "lstack").read_text(encoding="utf-8")
        self.assertIn('${staging}/lbrain/brain', content)
        self.assertIn('${CLAUDE_DIR}/lbrain/brain/', content)
        self.assertIn('docs/lbrain.md', content)
        self.assertTrue((ROOT / "lbrain" / "brain" / "decisions.py").exists())
        self.assertTrue((ROOT / "lbrain" / "brain" / "capture.py").exists())
        self.assertTrue((ROOT / "lbrain" / "brain" / "contracts.py").exists())
        self.assertTrue((ROOT / "lbrain" / "brain" / "autolearn.py").exists())
        self.assertTrue((ROOT / "scripts" / "lbrain-capture-hook.py").exists())

    def test_install_verifies_lbrain(self):
        content = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn('LBrain files installed', content)
        self.assertIn('brain status', content)


if __name__ == "__main__":
    unittest.main()

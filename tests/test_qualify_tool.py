"""The qualification runner itself: redaction and offline tier on this host."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.environ.get("PAT_QUALIFY_NESTED"), "already running inside the qualifier; do not recurse")
class QualifyToolTests(unittest.TestCase):
    def test_offline_tier_runs_here_and_redacts(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, PAT_HOME=str(Path(temp) / "home"))
            proc = subprocess.run([sys.executable, str(ROOT / "tools/qualify_windows.py"), "--tier", "offline",
                                   "--output", str(Path(temp) / "out"), "--allow-non-windows"],
                                  capture_output=True, text=True, cwd=ROOT, env=env, timeout=600)
            self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
            receipts = list((Path(temp) / "out").rglob("tier1-offline.json"))
            self.assertEqual(len(receipts), 1)
            data = json.loads(receipts[0].read_text())
            self.assertTrue(data["passed"])
            self.assertGreaterEqual(data["summary"]["steps"], 10)
            text = receipts[0].read_text()
            import getpass
            self.assertNotIn(getpass.getuser(), text.replace("<user>", ""))
            self.assertNotIn(temp, text, "work/home paths under the profile must be redacted or absent")

    def test_game_tier_without_collect_runs_nothing(self):
        proc = subprocess.run([sys.executable, str(ROOT / "tools/qualify_windows.py"), "--tier", "game",
                               "--output", "/tmp/never", "--allow-non-windows"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("runs nothing", proc.stderr)

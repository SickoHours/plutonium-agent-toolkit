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


class QualifyToolUnitTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("qualify_windows", ROOT / "tools" / "qualify_windows.py")
        self.q = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.q)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        (self.home / "game").mkdir(parents=True)

    def test_timeout_and_missing_program_become_structured_rows(self):
        row = self.q.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)
        self.assertEqual(row["exit_code"], 124)
        self.assertIn("timed out", row["stderr_head"])
        row = self.q.run(["/definitely/not/a/program"], timeout=5)
        self.assertEqual(row["exit_code"], 127)

    def test_tier3_collect_requires_begin_marker_and_checks_content_and_freshness(self):
        receipt = self.q.new_receipt("game")
        with self.assertRaises(SystemExit):
            self.q.tier_game_collect(receipt, self.home, None)
        state = self.home / "game"
        # Stale file written before the marker.
        (state / "last-load-check.json").write_text(json.dumps({"verified": True, "state_matches": True}))
        os.utime(state / "last-load-check.json", (1, 1))
        self.q.tier_game_begin(self.home)
        (state / "last-launch.json").write_text(json.dumps({"launch_requested": True, "game_detected": False}))
        (state / "last-load.json").write_text(json.dumps({"status": "engine-state-verified"}))
        (state / "last-result.json").write_text(json.dumps({"ok": True}))
        receipt = self.q.new_receipt("game")
        self.q.tier_game_collect(receipt, self.home, None)
        by_name = {s["name"]: s for s in receipt["steps"]}
        self.assertFalse(by_name["last-load-check.json"]["passed"])
        self.assertIn("stale", by_name["last-load-check.json"]["stderr_head"])
        self.assertFalse(by_name["last-launch.json"]["passed"], "game_detected false is not success")
        self.assertTrue(by_name["last-load.json"]["passed"])
        self.assertTrue(by_name["last-result.json"]["passed"])
        self.assertFalse(by_name["install-mod hello_zm receipt"]["passed"])

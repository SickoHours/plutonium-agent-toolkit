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

    def test_game_tier_begin_needs_no_output_directory(self):
        # docs/WINDOWS-QUALIFICATION.md runs `--tier game --begin` without --output; it writes only
        # the marker under PAT_HOME. Found on the first native Tier 3 attempt: argparse refused it.
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, PAT_HOME=str(Path(temp) / "home"))
            proc = subprocess.run([sys.executable, str(ROOT / "tools/qualify_windows.py"), "--tier", "game", "--begin",
                                   "--allow-non-windows"], capture_output=True, text=True, cwd=ROOT, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            marker = Path(temp) / "home" / "game" / "qualify-tier3-begin.json"
            self.assertTrue(marker.is_file())
            self.assertIn("began_unix", json.loads(marker.read_text(encoding="utf-8")))


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

    def test_finish_moves_an_existing_receipt_aside_instead_of_overwriting(self):
        # A rerun after a fix must not erase the failed attempt: RECORDING-A-RECEIPT.md keeps it.
        out = Path(self.temp.name) / "out"
        first = self.q.new_receipt("offline")
        first["steps"].append({"name": "x", "passed": False})
        self.q.finish(first, out, "tier1-offline.json", lambda value: value)
        second = self.q.new_receipt("offline")
        second["steps"].append({"name": "x", "passed": True})
        self.q.finish(second, out, "tier1-offline.json", lambda value: value)
        names = sorted(p.name for p in out.iterdir())
        superseded = [n for n in names if n.startswith("tier1-offline.superseded-") and n.endswith(".json")]
        self.assertEqual(len(superseded), 1, names)
        self.assertFalse(json.loads((out / superseded[0]).read_text(encoding="utf-8"))["passed"])
        latest = json.loads((out / "tier1-offline.json").read_text(encoding="utf-8"))
        self.assertTrue(latest["passed"])
        self.assertIn(superseded[0], json.dumps(latest["notes"]))

    def test_redactor_covers_any_users_path_regardless_of_account(self):
        # Maintainer finding on PR #7: a truncated excerpt (C:\Users\m), another account's path and
        # another drive's Users path all survived because only the exact USERPROFILE was known.
        from unittest.mock import patch

        with patch.dict(os.environ, {"USERPROFILE": r"C:\Users\maria"}):
            redact = self.q.redactor()
        cases = {
            r"C:\Users\m": "<userprofile>",
            r"C:\Users\maria\x": r"<userprofile>\x",
            r"C:\Users\someoneelse\z": r"<userprofile>\z",
            r"D:\Users\bob\y": r"<userprofile>\y",
            "C:/Users/maria/y": "<userprofile>/y",
            "C:\\\\Users\\\\m": "<userprofile>",  # JSON-escaped form, as private_scan quotes it
        }
        for raw, expected in cases.items():
            self.assertEqual(redact(raw), expected, raw)
        self.assertEqual(redact({"k": [r"C:\Users\m"]}), {"k": ["<userprofile>"]})

    def test_finish_strips_private_scan_excerpts(self):
        # The excerpt quotes the offending text itself; file, line and pattern are enough.
        hit = {"file": ".qualify-home/config.json", "line": 2, "pattern": "personal_home", "excerpt": "C:\\\\Users\\\\m"}
        receipt = self.q.new_receipt("offline")
        receipt["steps"].append({"name": "private scan", "passed": False, "json": {"ok": False, "hits": [hit]}})
        out = Path(self.temp.name) / "out"
        self.q.finish(receipt, out, "tier1-offline.json", self.q.redactor())
        saved = json.loads((out / "tier1-offline.json").read_text(encoding="utf-8"))["steps"][0]["json"]["hits"][0]
        self.assertNotIn("excerpt", saved)
        self.assertEqual((saved["file"], saved["line"], saved["pattern"]), (".qualify-home/config.json", 2, "personal_home"))

    def test_redact_existing_rewrites_a_committed_receipt_in_place_once(self):
        path = Path(self.temp.name) / "old.json"
        stale = {"schema_version": 1, "tier": "offline", "environment": {}, "notes": ["kept"],
                 "steps": [{"name": "private scan", "passed": False,
                            "json": {"ok": False, "hits": [{"file": "x.json", "line": 2, "pattern": "personal_home",
                                                             "excerpt": "C:\\\\Users\\\\m"}]}},
                           {"name": "unit tests", "passed": False, "stderr_head": r"D:\Users\bob\y failed"}]}
        path.write_text(json.dumps(stale, indent=2) + "\n", encoding="utf-8")
        argv = [sys.executable, str(ROOT / "tools/qualify_windows.py"), "--redact-existing", str(path)]
        proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)  # no --allow-non-windows: works anywhere
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("Users", text)
        data = json.loads(text)
        self.assertNotIn("excerpt", data["steps"][0]["json"]["hits"][0])
        self.assertIn(r"<userprofile>\y", data["steps"][1]["stderr_head"])
        self.assertEqual(data["notes"][0], "kept")
        self.assertTrue(any(isinstance(n, dict) and "re_redacted" in n for n in data["notes"]))
        # Idempotent: a second run changes nothing and adds no note.
        proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), text)

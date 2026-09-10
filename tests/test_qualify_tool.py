"""The qualification runner itself: redaction, platform identity and the offline tier on this host."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.environ.get("PAT_QUALIFY_NESTED"), "already running inside the qualifier; do not recurse")
class QualifyToolTests(unittest.TestCase):
    def test_offline_tier_runs_here_and_redacts(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, PAT_HOME=str(Path(temp) / "home"))
            proc = subprocess.run([sys.executable, str(ROOT / "tools/qualify.py"), "--tier", "offline",
                                   "--output", str(Path(temp) / "out"), "--allow-untested-platform"],
                                  capture_output=True, text=True, cwd=ROOT, env=env, timeout=600)
            self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
            receipts = list((Path(temp) / "out").rglob("*-tier1-offline.json"))
            self.assertEqual(len(receipts), 1)
            self.assertTrue(receipts[0].name.startswith(("windows-", "linux-", "darwin-")), receipts[0].name)
            data = json.loads(receipts[0].read_text())
            self.assertTrue(data["passed"])
            env_info = data["environment"]
            self.assertIn("os", env_info)
            self.assertIn("platform_token", env_info)
            self.assertEqual(env_info["native_windows"], os.name == "nt" and env_info["compatibility_layer"] is None)
            self.assertEqual(env_info["native_linux"], sys.platform.startswith("linux") and env_info["compatibility_layer"] is None)
            self.assertGreaterEqual(data["summary"]["steps"], 10)
            text = receipts[0].read_text()
            import getpass
            self.assertNotIn(getpass.getuser(), text.replace("<user>", ""))
            self.assertNotIn(temp, text, "work/home paths under the profile must be redacted or absent")

    def test_game_tier_without_collect_runs_nothing(self):
        proc = subprocess.run([sys.executable, str(ROOT / "tools/qualify.py"), "--tier", "game",
                               "--output", "/tmp/never", "--allow-untested-platform"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("runs nothing", proc.stderr)

    def test_game_tier_begin_needs_no_output_directory(self):
        # docs/WINDOWS-QUALIFICATION.md runs `--tier game --begin` without --output; it writes only
        # the marker under PAT_HOME. Found on the first native Tier 3 attempt: argparse refused it.
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, PAT_HOME=str(Path(temp) / "home"))
            proc = subprocess.run([sys.executable, str(ROOT / "tools/qualify.py"), "--tier", "game", "--begin",
                                   "--allow-untested-platform"], capture_output=True, text=True, cwd=ROOT, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            marker = Path(temp) / "home" / "game" / "qualify-tier3-begin.json"
            self.assertTrue(marker.is_file())
            self.assertIn("began_unix", json.loads(marker.read_text(encoding="utf-8")))


class QualifyToolUnitTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("qualify", ROOT / "tools" / "qualify.py")
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

    def test_tier3_collect_treats_non_object_and_corrupt_state_as_unreadable(self):
        # Macroscope on the Linux PR: a state file decoding to a list, or a corrupt install
        # receipt, crashed --collect instead of producing a failed receipt.
        state = self.home / "game"
        self.q.tier_game_begin(self.home)
        (state / "last-launch.json").write_text("[1, 2]")
        (state / "last-load.json").write_text("{not json")
        (state / "installs").mkdir()
        (state / "installs" / "hello_zm-1.json").write_text("null")
        receipt = self.q.new_receipt("game")
        self.q.tier_game_collect(receipt, self.home, None)
        by_name = {s["name"]: s for s in receipt["steps"]}
        self.assertFalse(by_name["last-launch.json"]["passed"])
        self.assertIn("expected an object", by_name["last-launch.json"]["stderr_head"])
        self.assertFalse(by_name["last-load.json"]["passed"])
        self.assertFalse(by_name["install-mod hello_zm receipt"]["passed"])
        self.assertIsNone(by_name["install-mod hello_zm receipt"]["json"])

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
        argv = [sys.executable, str(ROOT / "tools/qualify.py"), "--redact-existing", str(path)]
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

    def test_stage_for_tier3_refuses_to_rename_a_fastfile(self):
        # Native Tier 3 finding: hello_zm.ff copied to mod.ff could not be inflated and hung the client.
        built = Path(self.temp.name) / "packages" / "hello_zm.ff"
        built.parent.mkdir()
        built.write_bytes(b"ff")
        self.assertIsNone(self.q.stage_for_tier3(built, self.home))
        good = built.with_name("mod.ff")
        good.write_bytes(b"ff")
        staged = self.q.stage_for_tier3(good, self.home)
        self.assertEqual(staged, self.home / "qualify" / "hello_zm" / "mod.ff")
        self.assertEqual(staged.read_bytes(), b"ff")

    def test_redactor_handles_account_names_with_spaces(self):
        # Macroscope on PR #7: USERS_PATH stopped at whitespace, leaving "Doe\y" of "Jane Doe\y" in place.
        from unittest.mock import patch

        with patch.dict(os.environ, {"USERPROFILE": r"C:\Users\maria"}):
            redact = self.q.redactor()
        self.assertEqual(redact(r"D:\Users\Jane Doe\y"), r"<userprofile>\y")
        self.assertEqual(redact("D:\\\\Users\\\\Jane Doe\\\\y"), "<userprofile>\\\\y")
        self.assertEqual(redact("C:/Users/Jane Doe/y"), "<userprofile>/y")
        # Single-backslash raw strings here: the private scanner's own pattern rightly flags a
        # literal double-backslash C:\\Users\\<name> in source, and the redactor treats both alike.
        self.assertEqual(redact(r'path "E:\Users\Jane Doe" and more'), r'path "<userprofile>" and more')

    def test_redactor_covers_posix_home_paths_for_any_account(self):
        # Linux receipts carry /home/<name> in PAT_HOME, work and job paths; every account, not
        # just the current user, is replaced, including JSON-escaped and quoted forms.
        redact = self.q.redactor()
        # Paths are assembled at runtime so tools/private_scan.py does not flag this file.
        home = "/" + "home/"
        cases = {
            home + "alice/x": "<userprofile>/x",
            home + "bob": "<userprofile>",
            "/Users/carol/y": "<userprofile>/y",
            "/root/z": "<userprofile>/z",
            '"' + home + 'dave/w"': '"<userprofile>/w"',
            "see " + home + "eve/p and " + home + "frank/q": "see <userprofile>/p and <userprofile>/q",
        }
        for raw, expected in cases.items():
            self.assertEqual(redact(raw), expected, raw)
        # Not a home path: a relative folder that happens to be called home, and /homer.
        self.assertEqual(redact("data" + home + "x"), "data" + home + "x")
        self.assertEqual(redact("/homer/x"), "/homer/x")

    def test_redactor_covers_any_qualification_work_directory(self):
        # The first native Linux Tier 2 receipt leaked Tier 1's work directory: configure had
        # stored the fake storage path and doctor read it back under a different run.
        redact = self.q.redactor()
        temp = tempfile.gettempdir()
        raw = os.path.join(temp, "pat-qualify-offline-abc123", "fake-storage", "t6")
        self.assertEqual(redact(raw), os.path.join("<work>", "fake-storage", "t6"))
        # Other temp paths are untouched by this rule (the home rules may still apply to them).
        self.assertIn(os.path.join("unrelated", "x"), redact(os.path.join(temp, "unrelated", "x")))

    def test_tier3_receipt_fails_until_the_human_observations_are_true(self):
        # Macroscope on the first Linux PR: all state-file steps passed, every observation None,
        # and finish() emitted a passed receipt.
        out = Path(self.temp.name) / "out"
        receipt = self.q.new_receipt("game")
        receipt["steps"].append({"name": "last-load.json", "passed": True})
        receipt["human_observations"] = {"launcher_prompt_shown": None, "game_window_took_focus": None, "main_menu_reached": None,
                                         "town_spawn_playable": None, "hello_zm_line_visible_after_spawn": None,
                                         "quit_exited_cleanly": None, "plutonium_build": None, "notes": ""}
        self.assertFalse(self.q.finish(receipt, out, "windows-tier3-game.json", lambda v: v))
        for key in ("main_menu_reached", "town_spawn_playable", "hello_zm_line_visible_after_spawn", "quit_exited_cleanly"):
            receipt["human_observations"][key] = True
        receipt["notes"] = []
        self.assertTrue(self.q.finish(receipt, out, "windows-tier3-game.json", lambda v: v))

    @unittest.skipIf(os.environ.get("PAT_QUALIFY_NESTED"), "would recurse through the offline tier's unit-test step")
    def test_offline_tier_without_pat_home_uses_a_temporary_home(self):
        # High finding on the first Linux PR: with PAT_HOME unset the offline tier's configure step
        # wrote the fake storage path into the user's real config.json.
        env = {k: v for k, v in os.environ.items() if k != "PAT_HOME"}
        with tempfile.TemporaryDirectory() as temp:
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                proc = subprocess.run([sys.executable, str(ROOT / "tools/qualify.py"), "--tier", "offline",
                                       "--output", str(Path(temp) / "out"), "--allow-untested-platform"],
                                      capture_output=True, text=True, cwd=ROOT, env=env, timeout=600)
            self.assertEqual(proc.returncode, 0, proc.stdout[-1500:] + proc.stderr[-1500:])
            self.assertIn("temporary toolkit home", proc.stderr)
            receipts = list((Path(temp) / "out").rglob("*-tier1-offline.json"))
            data = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertTrue(data["environment"]["pat_home_isolated"])
            self.assertNotIn("pat-qualify-home-", receipts[0].read_text(encoding="utf-8"), "temporary home path is redacted")
            real_config = self.q.default_home() / "config.json"
            if real_config.is_file():
                self.assertNotIn("fake-storage", real_config.read_text(encoding="utf-8"))

    def test_compatibility_layers_are_refused_unless_allowed(self):
        # Macroscope on the first Linux PR: WSL passed the gate and could write linux-* receipts.
        from unittest.mock import patch

        argv = [str(ROOT / "tools/qualify.py"), "--tier", "offline", "--output", str(Path(self.temp.name) / "out")]
        with patch.object(self.q, "compatibility_layer", return_value="wsl"):
            self.assertEqual(self.q.compatibility_layer(), "wsl")
        # The gate lives in main(); exercise it through the module with the detector patched.
        with patch.object(self.q, "compatibility_layer", return_value="wsl"), patch.object(self.q.sys, "argv", argv), \
                patch.dict(os.environ, {"PAT_HOME": str(self.home)}):
            self.assertEqual(self.q.main(), 2)

    def test_environment_names_the_os_and_native_flags(self):
        info = self.q.environment()
        self.assertIn(info["platform_token"], ("windows", "linux", "darwin"))
        self.assertIsInstance(info["os"], str)
        self.assertTrue(info["os"])
        if os.name == "nt":
            self.assertIn("windows_build", info)
        else:
            self.assertIn("os_release", info)
            self.assertFalse(info["native_windows"])
        self.assertEqual(info["native_windows"] and info["native_linux"], False, "never both")

    def test_receipt_names_carry_the_platform_prefix(self):
        self.assertEqual(self.q.receipt_name("offline", "linux"), "linux-tier1-offline.json")
        self.assertEqual(self.q.receipt_name("backends", "windows"), "windows-tier2-backends.json")
        self.assertEqual(self.q.receipt_name("game", "windows"), "windows-tier3-game.json")

    def test_windows_shim_runs_the_generic_tool(self):
        # docs/WINDOWS-QUALIFICATION.md and the 0.1.0a1 receipts name tools/qualify_windows.py.
        proc = subprocess.run([sys.executable, str(ROOT / "tools/qualify_windows.py"), "--help"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--redact-existing", proc.stdout)
        self.assertIn("Windows or Linux", proc.stdout)

    def test_game_tier_is_refused_off_windows_unless_allowed(self):
        if os.name == "nt":
            self.skipTest("Windows runs the game tier natively")
        env = dict(os.environ, PAT_HOME=str(self.home))
        proc = subprocess.run([sys.executable, str(ROOT / "tools/qualify.py"), "--tier", "game", "--begin"],
                              capture_output=True, text=True, cwd=ROOT, env=env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("Windows", proc.stderr)

    @unittest.skipIf(os.environ.get("PAT_QUALIFY_NESTED"), "would recurse through the offline tier's unit-test step")
    def test_begin_without_output_is_refused_for_non_game_tiers(self):
        # Macroscope on PR #7: `--tier offline --begin` ran the whole tier and then crashed on a None output.
        # Before the fix this test recursed (tier -> unit tests -> this test -> tier), hence the guard above.
        env = dict(os.environ, PAT_HOME=str(self.home))
        for tier in ("offline", "backends"):
            proc = subprocess.run([sys.executable, str(ROOT / "tools/qualify.py"), "--tier", tier, "--begin"],
                                  capture_output=True, text=True, cwd=ROOT, env=env)
            self.assertEqual(proc.returncode, 2, f"{tier}: {proc.stderr[-300:]}")
            self.assertIn("--output", proc.stderr)

"""Game-control transition logic against a fake console. No Win32, no game, no worker.

Mirrors the reviewed regression set from the Linux and Windows-preview toolkits:
verified map settings before `map`, DLC5 zone guards, ordered mod transactions,
never-replay on uncertain delivery, receipt-bound check-load, private log counts.
"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.game import control, engine as engine_module
from plutonium_agent_toolkit.game.engine import ACK, Engine, parse_value

BASE = dict(fs_game="", mapname="zm_transit", sv_running="1", sv_cheats="0", g_gametype="zstandard")


class FakeConsole:
    def __init__(self):
        self.sent = []
        self.identity = {"pid": 42, "created": 123}

    def send(self, command, timeout=3):
        self.sent.append(command)


class FakeEngine:
    """State sequence per call; settings verify unless settings_ok is False."""

    def __init__(self, states):
        self.states = list(states)
        self.console = FakeConsole()
        self.verbs = []
        self.settings_ok = True

    def state(self, timeout=8):
        value = self.states.pop(0)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    def registered(self, verb):
        self.verbs.append(verb)

    def query(self, commands, timeout=8):
        self.console.sent.append(tuple(commands))
        rows = []
        for command in commands:
            if command.startswith("set "):
                name, value = command[4:].split(" ", 1)
                rows.append(f'"{name}" is: ' + (value if self.settings_ok else '"invalid"'))
        return rows


class GameFixture(unittest.TestCase):
    """setUp and helpers only; no tests, so subclasses do not re-run each other."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.environ["PAT_HOME"] = str(self.root / "home")
        self.addCleanup(lambda: os.environ.pop("PAT_HOME", None))
        self.storage = self.root / "storage" / "t6"
        self.storage.mkdir(parents=True)
        self.process = {"pid": 42, "created": 123}

    def mod(self, name="example", packaged=True):
        folder = self.storage / "mods" / name
        folder.mkdir(parents=True, exist_ok=True)
        if packaged:
            (folder / "mod.ff").write_bytes(b"fixture")
        return folder

    def change(self, engine, action, argument=None):
        return control.change(engine, action, argument, self.storage, self.process)

    def last_load(self):
        return json.loads((control.state_dir() / "last-load.json").read_text())



class GameControlTests(GameFixture):
    # ----- catalog and inventory -----
    def test_bus_depot_uses_the_engine_transit_token_for_survival(self):
        # T6 has no "busdepot" start location. Bus Depot survival is zstandard at location
        # "transit": Plutonium's mapvote maps zm_busdepot to "execgts zm_standard_transit.cfg
        # map zm_transit" and the cut-locations source registers
        # add_map_location_gamemode("zstandard", "transit", ...standard_station...).
        # TranZit classic is the same location with mode zclassic.
        maps = control.maps()
        self.assertEqual(maps["bus-depot"], {"label": "Bus Depot", "map": "zm_transit", "location": "transit",
                                             "mode": "zstandard", "group": "zsurvival", "dlc5": False})
        self.assertEqual((maps["tranzit"]["location"], maps["tranzit"]["mode"]), ("transit", "zclassic"))

    def test_map_catalog_is_complete_and_valid(self):
        maps = control.maps()
        self.assertEqual(len(maps), 18)
        self.assertEqual(maps["town"]["location"], "town")
        self.assertEqual(maps["town"]["group"], "zsurvival")
        self.assertTrue(maps["moon"]["dlc5"])
        self.assertFalse(maps["nuketown"]["dlc5"])

    def test_inventory_filters_unpackaged_and_multiplayer(self):
        self.mod()
        self.mod("mp_thing")
        self.mod("scripts_only", packaged=False)
        rows = {row["id"]: row for row in control.inventory(self.storage)}
        self.assertTrue(rows["example"]["available"])
        self.assertFalse(rows["mp_thing"]["available"])
        self.assertFalse(rows["scripts_only"]["available"])

    def test_mod_id_validation_and_escape(self):
        for bad in ("../x", ".", "a/b", "a\\b", "", "x" * 101):
            with self.assertRaises(Failure, msg=bad):
                control.mod_info(self.storage, bad)
        with self.assertRaises(Failure):
            control.mod_info(self.storage, "not_installed")

    def test_inventory_is_bounded(self):
        (self.storage / "mods").mkdir()
        for i in range(257):
            (self.storage / "mods" / str(i)).mkdir()
        with self.assertRaises(Failure):
            control.inventory(self.storage)

    # ----- engine parsing -----
    def test_pending_value_belongs_to_its_field(self):
        lines = ['"g_gametype" is: "zclassic"', 'latched: "zstandard"', '"other" is: "x"', 'latched: "bad"']
        self.assertEqual(parse_value(lines, "g_gametype", pending=True), "zstandard")
        self.assertEqual(parse_value(lines, "g_gametype"), "zclassic")

    def test_query_only_accepts_allowlist_and_sends_nothing_otherwise(self):
        console = FakeConsole()
        for commands in (("quit",), ("god",), ('set fs_game "mods/evil"',), ("sv_running",) * 11):
            with self.assertRaises(Failure):
                Engine(console).query(commands)
        self.assertEqual(console.sent, [])

    def test_query_requires_its_own_fresh_markers(self):
        class FreshConsole(FakeConsole):
            def screen(self):
                parts = self.sent[-1].split(";")
                start = parts[0].split('"')[1]
                end = parts[-2].split('"')[1]
                return ['"fs_game" is: "old"', f'"{ACK}" is: "{start}"', '"fs_game" is: "mods/new"', f'"{ACK}" is: "{end}"']
        console = FreshConsole()
        rows = Engine(console).query(("fs_game",))
        self.assertEqual(parse_value(rows, "fs_game"), "mods/new")
        self.assertEqual(len(console.sent), 1)

    def test_query_timeout_is_delivery_uncertain_and_not_replayed(self):
        console = FakeConsole()
        console.screen = lambda: ['"fs_game" is: "stale"']
        with self.assertRaises(Failure) as ctx:
            Engine(console).query(("fs_game",), timeout=0)
        self.assertEqual(ctx.exception.code, "delivery_uncertain")
        self.assertEqual(len(console.sent), 1)

    # ----- transitions -----
    def test_map_settings_verified_before_map_and_sent_once(self):
        engine = FakeEngine([BASE, BASE])
        result = self.change(engine, "load-map", "town")
        self.assertFalse(result["ready_for_handoff"])
        self.assertEqual(result["load_check"]["argv"], ["pat", "game", "check-load", result["load_id"]])
        self.assertEqual(engine.console.sent[-1], "map zm_transit")
        self.assertEqual(engine.console.sent.count("map zm_transit"), 1)
        self.assertIn('set ui_zm_mapstartlocation "town"', engine.console.sent[0])
        self.assertEqual(self.last_load()["status"], "engine-state-verified")

    def test_bad_map_settings_prevent_gameplay_submission(self):
        engine = FakeEngine([BASE])
        engine.settings_ok = False
        with self.assertRaises(Failure) as ctx:
            self.change(engine, "load-map", "town")
        self.assertEqual(ctx.exception.code, "delivery_uncertain")
        self.assertFalse(any(isinstance(v, str) and v.startswith("map ") for v in engine.console.sent))
        self.assertEqual(self.last_load()["status"], "unverified")

    def test_unknown_map_and_dlc5_without_mod_send_nothing(self):
        engine = FakeEngine([BASE])
        with self.assertRaises(Failure):
            self.change(engine, "load-map", "not-a-map")
        engine = FakeEngine([BASE])
        with self.assertRaises(Failure):
            self.change(engine, "load-map", "moon")
        self.assertEqual(engine.console.sent, [])

    def test_dlc5_requires_zone_in_selected_mod(self):
        folder = self.mod("dlc5")
        before = dict(BASE, fs_game="mods/dlc5")
        engine = FakeEngine([before])
        with self.assertRaises(Failure) as ctx:
            self.change(engine, "load-map", "moon")
        self.assertEqual(ctx.exception.code, "input_missing")
        (folder / "zone").mkdir()
        (folder / "zone" / "zm_moon.ff").write_bytes(b"zone")
        engine = FakeEngine([before, dict(before, mapname="zm_moon", g_gametype="zclassic")])
        result = self.change(engine, "load-map", "moon")
        self.assertEqual(engine.console.sent[-1], "map zm_moon")
        self.assertIn("load_id", result)

    def test_restart_requires_local_match(self):
        engine = FakeEngine([dict(BASE, sv_running="0")])
        with self.assertRaises(Failure):
            self.change(engine, "fast-restart")
        self.assertEqual(engine.console.sent, [])

    def test_uncertain_restart_is_never_replayed_and_recorded(self):
        engine = FakeEngine([BASE, Failure("delivery_uncertain", "timeout")])
        with self.assertRaises(Failure) as ctx:
            self.change(engine, "fast-restart")
        self.assertEqual(engine.console.sent, ["fast_restart"])
        self.assertIn("load_id", ctx.exception.details)
        self.assertEqual(self.last_load()["status"], "unverified")

    def test_wrong_state_after_command_is_not_success(self):
        for field, value in (("mapname", "zm_tomb"), ("fs_game", "mods/changed"), ("sv_running", "0")):
            engine = FakeEngine([BASE, dict(BASE, **{field: value})])
            with self.assertRaises(Failure, msg=field):
                self.change(engine, "fast-restart")
            self.assertEqual(engine.console.sent, ["fast_restart"])

    def test_selected_mod_is_noop_and_ends_no_match(self):
        self.mod()
        engine = FakeEngine([dict(BASE, fs_game="mods/example")])
        self.assertTrue(self.change(engine, "select-mod", "example")["no_op"])
        self.assertEqual(engine.console.sent, [])

    def test_failed_disconnect_stops_mod_transaction(self):
        self.mod()
        engine = FakeEngine([BASE, BASE])  # sv_running stays 1 after disconnect
        with self.assertRaises(Failure):
            self.change(engine, "select-mod", "example")
        self.assertEqual(engine.console.sent, ["disconnect"])

    def test_unverified_unload_prevents_target_load(self):
        self.mod()
        before = dict(BASE, fs_game="mods/old", sv_running="0")
        self.mod("old")
        engine = FakeEngine([before, before])  # fs_game stays after loadmod ""
        with self.assertRaises(Failure):
            self.change(engine, "select-mod", "example")
        self.assertEqual(engine.console.sent, ['loadmod ""'])

    def test_reload_orders_verified_transitions(self):
        self.mod()
        before = dict(BASE, fs_game="mods/example")
        idle = dict(before, sv_running="0")
        engine = FakeEngine([before, idle, dict(idle, fs_game=""), idle])
        result = self.change(engine, "reload-mod")
        self.assertIn("load_id", result)
        self.assertEqual(engine.console.sent, ["disconnect", 'loadmod ""', "loadmod mods/example"])

    def test_select_base_unloads_without_loading(self):
        self.mod("old")
        before = dict(BASE, fs_game="mods/old", sv_running="0")
        engine = FakeEngine([before, dict(before, fs_game=""), dict(before, fs_game="")])
        self.change(engine, "select-mod", "base")
        self.assertEqual(engine.console.sent, ['loadmod ""'])

    def test_unavailable_mod_is_refused_before_transport(self):
        self.mod("mp_x")
        engine = FakeEngine([BASE])
        with self.assertRaises(Failure):
            self.change(engine, "select-mod", "mp_x")
        self.assertEqual(engine.console.sent, [])

    # ----- logs and check-load -----
    def test_log_check_counts_errors_without_returning_raw_lines(self):
        log = self.storage / "main" / "console_zm.log"
        log.parent.mkdir()
        log.write_bytes(b"old\n")
        cursors = {"zombies": control._log_cursor(log)}
        with log.open("ab") as stream:
            stream.write(b"token=PRIVATE\nscript runtime error: fixture\n")
        result = control.inspect_logs(self.storage, cursors)
        self.assertEqual(result["zombies"]["error_lines"], 1)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_rotated_and_oversized_logs_are_unverified(self):
        log = self.storage / "main" / "console_zm.log"
        log.parent.mkdir()
        log.write_bytes(b"first\n")
        cursors = {"zombies": control._log_cursor(log)}
        log.write_bytes(b"second\n")
        self.assertFalse(control.inspect_logs(self.storage, cursors)["zombies"]["checked"])
        cursors = {"zombies": control._log_cursor(log)}
        with log.open("ab") as stream:
            stream.write(b"x" * (control.MAX_LOG_TAIL + 1))
        self.assertFalse(control.inspect_logs(self.storage, cursors)["zombies"]["checked"])

    def test_old_or_wrong_load_id_does_not_attach(self):
        control._save(control.state_dir() / "last-load.json", {"id": "a" * 32, "created": 0})
        with self.assertRaises(Failure):
            control.check_load("a" * 32, self.storage, lambda **_: self.fail("must not attach"))
        with self.assertRaises(Failure):
            control.check_load("not-an-id", self.storage, lambda **_: self.fail("must not attach"))

    def test_failed_original_load_stays_failed_even_if_state_now_matches(self):
        engine = FakeEngine([BASE, Failure("delivery_uncertain", "timeout")])
        with self.assertRaises(Failure) as ctx:
            self.change(engine, "fast-restart")
        load_id = ctx.exception.details["load_id"]

        class Context:
            def __enter__(self):
                return FakeConsole()

            def __exit__(self, *_):
                return False

        with patch.object(Engine, "state", return_value=BASE), \
             patch.object(control, "inspect_logs", return_value={"zombies": {"checked": True, "error_lines": 0}}):
            result = control.check_load(load_id, self.storage, lambda **_: Context())
        self.assertFalse(result["verified"])
        self.assertTrue(result["state_matches"])
        self.assertEqual(result["original_status"], "unverified")

    # ----- quit -----
    def test_quit_sends_once_and_reports_uncertain_if_process_survives(self):
        class StubK:
            def WaitForSingleObject(self, *_):
                return 258  # still running
        console = FakeConsole()
        console.k, console.process = StubK(), 1
        engine = FakeEngine([BASE])
        engine.console = console
        with patch.object(control.time, "monotonic", side_effect=[0, 0, 100]):
            with self.assertRaises(Failure) as ctx:
                self.change(engine, "quit")
        self.assertEqual(ctx.exception.code, "delivery_uncertain")
        self.assertEqual(console.sent, ["quit"])


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["PAT_HOME"] = self.temp.name
        self.addCleanup(lambda: os.environ.pop("PAT_HOME", None))

    def completed(self, stdout, returncode=0):
        class Completed:
            pass
        c = Completed()
        c.stdout, c.returncode = stdout, returncode
        return c

    def test_dispatch_spawns_one_worker_and_relays_structured_failure(self):
        payload = json.dumps({"ok": False, "error_code": "game_not_found", "message": "no window"}).encode()
        with patch.object(control.subprocess, "run", return_value=self.completed(payload, 1)) as run:
            result = control.dispatch("info", None)
        run.assert_called_once()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "game_not_found")
        self.assertIn("request_id", result)

    def test_timeout_and_malformed_output_are_delivery_uncertain(self):
        with patch.object(control.subprocess, "run", side_effect=control.subprocess.TimeoutExpired("x", 110)):
            with self.assertRaises(Failure) as ctx:
                control.dispatch("load-map", "town")
        self.assertEqual(ctx.exception.code, "delivery_uncertain")
        with patch.object(control.subprocess, "run", return_value=self.completed(b"not json")):
            with self.assertRaises(Failure) as ctx:
                control.dispatch("info", None)
        self.assertEqual(ctx.exception.code, "delivery_uncertain")
        with patch.object(control.subprocess, "run", return_value=self.completed(json.dumps({"ok": True}).encode(), 1)):
            with self.assertRaises(Failure) as ctx:
                control.dispatch("info", None)
        self.assertEqual(ctx.exception.code, "delivery_uncertain")

    def test_non_live_action_is_refused_before_spawning(self):
        with patch.object(control.subprocess, "run") as run:
            with self.assertRaises(Failure):
                control.dispatch("mods", None)
        run.assert_not_called()


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["PAT_HOME"] = self.temp.name
        self.addCleanup(lambda: os.environ.pop("PAT_HOME", None))
        launcher = Path(self.temp.name) / "plutonium.exe"
        launcher.write_bytes(b"MZ")
        from plutonium_agent_toolkit.core import config
        config.save({"plutonium_launcher": str(launcher)})

    def make_native(self, window_sequence, foreground_sequence):
        class Native:
            calls = {"windows": 0, "fg": 0}

            @staticmethod
            def windows():
                i = min(Native.calls["windows"], len(window_sequence) - 1)
                Native.calls["windows"] += 1
                return window_sequence[i]

            @staticmethod
            def foreground():
                i = min(Native.calls["fg"], len(foreground_sequence) - 1)
                Native.calls["fg"] += 1
                return foreground_sequence[i]
        return Native

    def test_launch_uses_fixed_uri_and_reports_focus_separately(self):
        native = self.make_native([{}, {}, {4242: "Plutonium T6 Zombies (r5346)"}],
                                  [{"pid": 1, "title": "agent"}, {"pid": 1, "title": "agent"}, {"pid": 9, "title": "Plutonium Launcher"}])
        opened = []
        clock = iter([0.0] + [0.3 * i for i in range(1, 400)])
        with patch.object(control.os, "startfile", lambda uri: opened.append(uri), create=True), \
             patch.object(control.time, "sleep", lambda *_: None), \
             patch.object(control.time, "monotonic", lambda: next(clock)):
            result = control.launch(native, None, observe_seconds=90, settle_seconds=2)
        self.assertEqual(opened, ["plutonium://play/t6zm"])
        self.assertTrue(result["launch_requested"])
        self.assertTrue(result["game_detected"])
        self.assertEqual(result["game_window"]["pid"], 4242)
        self.assertFalse(result["focus_preserved"])
        self.assertTrue(any(e["event"] == "foreground-changed" for e in result["focus_events"]))
        self.assertFalse(result["ready_for_handoff"])

    def test_launch_refuses_when_game_already_running_and_without_launcher(self):
        native = self.make_native([{7: "Plutonium T6 Zombies"}], [{"pid": 1, "title": ""}])
        with patch.object(control.os, "startfile", side_effect=AssertionError("must not launch"), create=True):
            result = control.launch(native, None)
        self.assertTrue(result["already_running"])
        from plutonium_agent_toolkit.core import config
        (Path(self.temp.name) / "config.json").unlink()
        native = self.make_native([{}], [{"pid": 1, "title": ""}])
        with patch.object(control.os, "startfile", side_effect=AssertionError("must not launch"), create=True):
            with self.assertRaises(Failure) as ctx:
                control.launch(native, None)
        self.assertEqual(ctx.exception.code, "config_missing")


if __name__ == "__main__":
    unittest.main()


class CliGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["PAT_HOME"] = self.temp.name
        self.addCleanup(lambda: os.environ.pop("PAT_HOME", None))

    def invoke(self, argv):
        import contextlib
        import io

        from plutonium_agent_toolkit.cli import entry

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = entry(argv)
        return code, json.loads(buf.getvalue())

    def test_live_routes_are_gated_and_mods_needs_storage(self):
        if os.name == "nt":
            self.skipTest("gate does not apply on Windows")
        for argv in (["game", "status"], ["game", "info"], ["game", "launch"], ["game", "load-map", "town"], ["game", "quit"]):
            code, row = self.invoke(argv)
            self.assertEqual(code, 1, argv)
            self.assertEqual(row["error_code"], "unsupported_platform", argv)
        code, row = self.invoke(["game", "mods"])
        self.assertEqual(row["error_code"], "config_missing")
        storage = Path(self.temp.name) / "s"
        (storage / "mods" / "abc").mkdir(parents=True)
        (storage / "mods" / "abc" / "mod.ff").write_bytes(b"x")
        self.invoke(["configure", "--plutonium-storage-t6", str(storage)])
        code, row = self.invoke(["game", "mods"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["mods"][0]["id"], "abc")
        self.assertFalse(row["result"]["game_queried"])

    def test_unknown_game_action_is_usage_error(self):
        code, row = self.invoke(["game", "god"])
        self.assertEqual(code, 2)

    def test_manifest_marks_game_routes_implemented(self):
        _, row = self.invoke(["manifest"])
        by_id = {r["id"]: r for r in row["result"]["routes"]}
        for rid in ("game.launch", "game.load-map", "game.check-load", "game.quit", "game.mods"):
            self.assertEqual(by_id[rid]["status"], "implemented", rid)


class WorkerGuardTests(unittest.TestCase):
    def test_direct_worker_invocation_is_refused_before_any_native_call(self):
        import contextlib
        import io

        from plutonium_agent_toolkit.game import worker

        os.environ.pop(control.WORKER_TOKEN_ENV, None)
        with patch.object(control, "execute_worker", side_effect=AssertionError("must not execute")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = worker.main(["quit", ""])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(buf.getvalue())["error_code"], "invalid_arguments")

    def test_worker_with_token_still_requires_native_windows(self):
        import contextlib
        import io

        from plutonium_agent_toolkit.game import worker

        os.environ[control.WORKER_TOKEN_ENV] = "a" * 32
        try:
            with patch.object(control, "execute_worker", side_effect=AssertionError("must not execute")), \
                 patch("plutonium_agent_toolkit.core.platform.is_windows", return_value=True), \
                 patch("plutonium_agent_toolkit.core.platform.is_wine", return_value=True):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = worker.main(["quit", ""])
        finally:
            os.environ.pop(control.WORKER_TOKEN_ENV, None)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(buf.getvalue())["error_code"], "unsupported_platform")

    def test_dispatch_passes_a_one_shot_token(self):
        seen = {}

        def fake_run(argv, **kwargs):
            seen["token"] = kwargs["env"].get(control.WORKER_TOKEN_ENV)

            class Completed:
                stdout = json.dumps({"ok": True}).encode()
                returncode = 0
            return Completed()

        with patch.object(control.subprocess, "run", side_effect=fake_run):
            result = control.dispatch("status", None)
        self.assertRegex(seen["token"], r"^[0-9a-f]{32}$")
        self.assertEqual(result["request_id"], seen["token"])


class ArgumentValidationTests(unittest.TestCase):
    def test_extra_argument_on_no_argument_action_is_refused_before_worker(self):
        with patch.object(control.subprocess, "run") as run:
            for action in ("quit", "info", "status", "launch", "reload-mod", "fast-restart", "disconnect"):
                with self.assertRaises(Failure, msg=action) as ctx:
                    control.dispatch(action, "typo")
                self.assertEqual(ctx.exception.code, "input_invalid")
        run.assert_not_called()

    def test_required_argument_actions_need_one(self):
        with patch.object(control.subprocess, "run") as run:
            for action in ("select-mod", "load-map", "check-load"):
                with self.assertRaises(Failure, msg=action):
                    control.dispatch(action, None)
        run.assert_not_called()

    def test_worker_side_validation_also_refuses(self):
        with self.assertRaises(Failure):
            control.validate_argument("quit", "typo")
        control.validate_argument("quit", None)
        control.validate_argument("load-map", "town")


class FourthReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["PAT_HOME"] = self.temp.name
        self.addCleanup(lambda: os.environ.pop("PAT_HOME", None))
        self.storage = Path(self.temp.name) / "s"
        (self.storage / "main").mkdir(parents=True)

    def test_pre_load_error_lines_do_not_count(self):
        log = self.storage / "main" / "console_zm.log"
        log.write_bytes(b"script runtime error: BEFORE the load\n")
        cursors = {"zombies": control._log_cursor(log)}
        with log.open("ab") as stream:
            stream.write(b"loading fine\n")
        result = control.inspect_logs(self.storage, cursors)
        self.assertTrue(result["zombies"]["checked"])
        self.assertEqual(result["zombies"]["error_lines"], 0)
        self.assertEqual(result["zombies"]["bytes"], len(b"loading fine\n"))

    def test_focus_preserved_uses_the_full_log_even_when_truncated(self):
        launcher = Path(self.temp.name) / "plutonium.exe"
        launcher.write_bytes(b"MZ")
        from plutonium_agent_toolkit.core import config
        config.save({"plutonium_launcher": str(launcher)})
        # 250 distinct foreground titles, then the game appears.
        fg = [{"pid": i, "title": f"w{i}"} for i in range(251)]
        windows_seq = [{}] * 260 + [{99: "Plutonium T6 Zombies"}]

        class Native:
            fi = wi = 0

            @staticmethod
            def foreground():
                Native.fi += 1
                return fg[min(Native.fi - 1, len(fg) - 1)]

            @staticmethod
            def windows():
                Native.wi += 1
                return windows_seq[min(Native.wi - 1, len(windows_seq) - 1)]

        import itertools
        ticks = (i * 0.01 for i in itertools.count())
        with patch.object(control.os, "startfile", lambda uri: None, create=True), \
             patch.object(control.time, "sleep", lambda *_: None), \
             patch.object(control.time, "monotonic", lambda: next(ticks)):
            result = control.launch(Native, None, observe_seconds=90, settle_seconds=1)
        self.assertTrue(result["focus_events_truncated"])
        self.assertEqual(len(result["focus_events"]), 200)
        self.assertGreater(result["focus_event_count"], 200)
        self.assertFalse(result["focus_preserved"])


class FifthReviewRegressionTests(GameFixture):
    def test_reload_refuses_unpackaged_or_multiplayer_selected_mod(self):
        self.mod("scripts_only", packaged=False)
        engine = FakeEngine([dict(BASE, fs_game="mods/scripts_only")])
        with self.assertRaises(Failure) as ctx:
            self.change(engine, "reload-mod")
        self.assertEqual(ctx.exception.code, "input_invalid")
        self.assertEqual(engine.console.sent, [])
        self.assertEqual(engine.verbs, [], "no registered-verb check before rejection")
        self.mod("mp_x")
        engine = FakeEngine([dict(BASE, fs_game="mods/mp_x")])
        with self.assertRaises(Failure):
            self.change(engine, "reload-mod")
        self.assertEqual(engine.console.sent, [])

    def test_quit_does_not_require_storage_configuration(self):
        # No plutonium_storage_t6 configured in this PAT_HOME.
        from plutonium_agent_toolkit.game import control as c

        class StubConsole:
            identity = {"pid": 1, "created": 2}
            sent = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        captured = {}

        def fake_change(engine, action, argument, root, process):
            captured["root"] = root
            return {"stopped": True}

        class FakeNative:
            @staticmethod
            def lock():
                import contextlib
                return contextlib.nullcontext()
            Console = StubConsole

        os.environ[c.WORKER_TOKEN_ENV] = "b" * 32
        try:
            with patch.dict("sys.modules", {"plutonium_agent_toolkit.game.native": FakeNative}), \
                 patch.object(c, "change", side_effect=fake_change):
                result = c.execute_worker("quit", None)
        finally:
            os.environ.pop(c.WORKER_TOKEN_ENV, None)
        self.assertTrue(result["stopped"])
        self.assertIsNone(captured["root"])


class LaunchSettleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["PAT_HOME"] = self.temp.name
        self.addCleanup(lambda: os.environ.pop("PAT_HOME", None))
        launcher = Path(self.temp.name) / "plutonium.exe"
        launcher.write_bytes(b"MZ")
        from plutonium_agent_toolkit.core import config
        config.save({"plutonium_launcher": str(launcher)})

    def test_focus_change_after_detection_is_still_recorded(self):
        # Game visible from the first poll; the launcher steals focus 5 s after detection.
        class Native:
            calls = 0
            window_calls = 0

            @staticmethod
            def windows():
                Native.window_calls += 1
                return {} if Native.window_calls == 1 else {7: "Plutonium T6 Zombies"}

            @staticmethod
            def foreground():
                Native.calls += 1
                return {"pid": 9, "title": "Plutonium Launcher"} if Native.calls > 20 else {"pid": 1, "title": "agent"}

        import itertools
        clock = (0.25 * i for i in itertools.count())
        with patch.object(control.os, "startfile", lambda uri: None, create=True), \
             patch.object(control.time, "sleep", lambda *_: None), \
             patch.object(control.time, "monotonic", lambda: next(clock)):
            result = control.launch(Native, None, observe_seconds=90, settle_seconds=15)
        self.assertTrue(result["game_detected"])
        self.assertFalse(result["focus_preserved"])
        events = [e["event"] for e in result["focus_events"]]
        self.assertIn("game-detected", events)
        self.assertLess(events.index("game-detected"), events.index("foreground-changed"), "change came after detection")
        self.assertGreaterEqual(result["focus_observed_seconds"], 15)
        self.assertLess(result["focus_observed_seconds"], 90)
        self.assertIn("15s after the game window appeared", result["focus_scope"])

    def test_without_a_game_window_the_full_interval_is_observed(self):
        class Native:
            @staticmethod
            def windows():
                return {}

            @staticmethod
            def foreground():
                return {"pid": 1, "title": "agent"}

        import itertools
        clock = (0.5 * i for i in itertools.count())
        with patch.object(control.os, "startfile", lambda uri: None, create=True), \
             patch.object(control.time, "sleep", lambda *_: None), \
             patch.object(control.time, "monotonic", lambda: next(clock)):
            result = control.launch(Native, None, observe_seconds=20)
        self.assertFalse(result["game_detected"])
        self.assertGreaterEqual(result["focus_observed_seconds"], 20)
        self.assertIn("never appeared", result["focus_scope"])


class SixthReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["PAT_HOME"] = self.temp.name
        self.addCleanup(lambda: os.environ.pop("PAT_HOME", None))

    def test_every_live_action_has_a_deadline_that_covers_its_internal_waits(self):
        self.assertEqual(set(control.WORKER_DEADLINES), control.LIVE_ACTIONS)
        # Mod transaction: before(8) + verb checks(2x8) + disconnect send(3)+state(30) + unload send(3)+state(30) + load send(3)+state(40)
        self.assertGreater(control.WORKER_DEADLINES["select-mod"], 8 + 16 + 3 + 30 + 3 + 30 + 3 + 40)
        self.assertGreater(control.WORKER_DEADLINES["reload-mod"], 8 + 16 + 3 + 30 + 3 + 30 + 3 + 40)
        # Map load: before(8) + verb(8) + settings query(8) + send(3) + state(40)
        self.assertGreater(control.WORKER_DEADLINES["load-map"], 8 + 8 + 8 + 3 + 40)
        # Launch: observe(90) + settle(15)
        self.assertGreater(control.WORKER_DEADLINES["launch"], 90 + control.LAUNCH_SETTLE_SECONDS)
        # Quit: before(8) + verb(8) + send(3) + 20 s wait
        self.assertGreater(control.WORKER_DEADLINES["quit"], 8 + 8 + 3 + 20)

    def test_dispatch_uses_the_per_action_deadline(self):
        seen = {}

        def fake_run(argv, **kwargs):
            seen["timeout"] = kwargs["timeout"]

            class Completed:
                stdout = json.dumps({"ok": True}).encode()
                returncode = 0
            return Completed()

        with patch.object(control.subprocess, "run", side_effect=fake_run):
            control.dispatch("select-mod", "x")
        self.assertEqual(seen["timeout"], control.WORKER_DEADLINES["select-mod"])
        with patch.object(control.subprocess, "run", side_effect=control.subprocess.TimeoutExpired("x", 200)):
            with self.assertRaises(Failure) as ctx:
                control.dispatch("select-mod", "x")
        self.assertIn("200-second", ctx.exception.message)

    def test_unregistered_uri_handler_is_a_structured_config_failure(self):
        launcher = Path(self.temp.name) / "plutonium.exe"
        launcher.write_bytes(b"MZ")
        from plutonium_agent_toolkit.core import config
        config.save({"plutonium_launcher": str(launcher)})

        class Native:
            @staticmethod
            def windows():
                return {}

            @staticmethod
            def foreground():
                return {"pid": 1, "title": "agent"}

        def refuse(uri):
            raise OSError(1155, "No application is associated with the specified file for this operation")

        with patch.object(control.os, "startfile", refuse, create=True):
            with self.assertRaises(Failure) as ctx:
                control.launch(Native, None)
        self.assertEqual(ctx.exception.code, "config_missing")
        self.assertFalse(ctx.exception.details["launch_requested"])
        self.assertIn("no launch request was issued", ctx.exception.message)

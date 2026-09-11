"""``pat plane``: the typed action table, argument validation, and the loopback server driving
``pat`` children against the fake backends. No real backend, no network beyond 127.0.0.1, no game."""
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from plutonium_agent_toolkit.cli import JOB_GROUPS
from plutonium_agent_toolkit.core.discovery import find, routes
from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.plane import actions as actions_module
from plutonium_agent_toolkit.plane import server as server_module
from plutonium_agent_toolkit.plane.actions import ACTIONS, BY_ID, argv_for, table
from tests.test_dev_routes import DevRouteFixture, invoke

ROOT = Path(__file__).resolve().parents[1]


class ActionTableTests(unittest.TestCase):
    def test_every_action_is_one_registered_route_with_the_right_job_flag(self):
        ids = [a.id for a in ACTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        for action in ACTIONS:
            group, _, name = action.route.partition(" ")
            if name:
                find(group, name)  # raises for an unknown route
            self.assertEqual(action.job, group in JOB_GROUPS, f"{action.id}: job routes are exactly the --output routes")
            for param in action.params:
                self.assertTrue(param.name.replace("_", "").isalnum())
                if param.kind == "path":
                    self.assertTrue(param.file, f"{action.id}.{param.name}: a path parameter names the file it must end in")

    def test_state_changing_actions_ask_for_confirmation(self):
        for action in ACTIONS:
            group, _, name = action.route.partition(" ")
            route = find(group, name) if name else None
            if route and route.effect in ("changes-game", "query-engine"):
                self.assertTrue(action.confirm, f"{action.id} talks to the game and must confirm")
            if route and group == "agent" and route.effect == "writes-output":
                self.assertTrue(action.confirm, f"{action.id} writes to the agent host and must confirm")

    def test_table_marks_windows_routes_unavailable_off_windows(self):
        rows = table({"system": "Linux", "game_control_supported": False})
        by_id = {r["id"]: r for r in rows}
        self.assertFalse(by_id["game-launch"]["available_here"])
        self.assertTrue(by_id["game-launch"]["requires_windows"])
        self.assertTrue(by_id["module-plan"]["available_here"])
        self.assertTrue(by_id["game-install-mod"]["available_here"], "install-mod is a file copy on any OS")
        rows = table({"system": "Windows", "game_control_supported": True})
        self.assertTrue({r["id"]: r for r in rows}["game-launch"]["available_here"])

    def test_plane_actions_route_lists_the_table(self):
        code, row = invoke(["plane", "actions"])
        self.assertEqual(code, 0, row)
        self.assertEqual([a["id"] for a in row["result"]["actions"]], [a.id for a in ACTIONS])
        by_id = {r.id: r for r in routes()}
        self.assertEqual(by_id["plane.serve"].effect, "serves-local")
        self.assertEqual(by_id["plane.actions"].effect, "inert")


class ArgvTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lib = self.root / "lib"
        self.jobs = self.root / "jobs"
        (self.lib / "pack").mkdir(parents=True)
        (self.lib / "pack" / "composition.json").write_text("{}")
        (self.jobs / "build-1" / "packages").mkdir(parents=True)
        (self.jobs / "build-1" / "packages" / "mod.ff").write_bytes(b"ff")
        (self.jobs / "build-1" / "receipt.json").write_text("{}")
        self.prompts = self.root / "prompts"

    def argv(self, action_id, args):
        return argv_for(BY_ID[action_id], args, [self.lib], self.jobs, self.prompts)

    def test_paths_resolve_only_inside_their_roots_and_end_in_the_named_file(self):
        argv = self.argv("module-plan", {"composition": {"root": 0, "path": "pack/composition.json"}})
        self.assertEqual(argv, ["module", "plan", str(self.lib / "pack" / "composition.json")])
        for bad in ({"root": 0, "path": "../pack/composition.json"}, {"root": 0, "path": "/etc/composition.json"},
                    {"root": 0, "path": "pack/../pack/composition.json"}, {"root": 1, "path": "pack/composition.json"},
                    {"root": "jobs", "path": "build-1/receipt.json"}, "pack/composition.json", {"path": "pack/composition.json"},
                    {"root": 0, "path": "pack\\composition.json"}, {"root": True, "path": "pack/composition.json"}):
            with self.assertRaises(Failure, msg=repr(bad)) as ctx:
                self.argv("module-plan", {"composition": bad})
            self.assertEqual(ctx.exception.code, "input_invalid", repr(bad))
        with self.assertRaises(Failure) as ctx:
            self.argv("module-plan", {"composition": {"root": 0, "path": "missing/composition.json"}})
        self.assertEqual(ctx.exception.code, "input_missing")
        argv = self.argv("project-verify", {"receipt": {"root": "jobs", "path": "build-1/receipt.json"}, "inputs": True})
        self.assertEqual(argv, ["project", "verify", str(self.jobs / "build-1" / "receipt.json"), "--inputs"])
        with self.assertRaises(Failure):
            self.argv("project-verify", {"receipt": {"root": 0, "path": "pack/composition.json"}})

    def test_links_are_refused(self):
        if os.name == "nt":
            self.skipTest("symlink creation needs a privilege on Windows")
        (self.lib / "linked").symlink_to(self.lib / "pack")
        with self.assertRaises(Failure) as ctx:
            self.argv("module-plan", {"composition": {"root": 0, "path": "linked/composition.json"}})
        self.assertEqual(ctx.exception.code, "input_invalid")

    def test_unknown_required_and_typed_parameters(self):
        with self.assertRaises(Failure) as ctx:
            self.argv("module-plan", {"composition": {"root": 0, "path": "pack/composition.json"}, "output": "/tmp/x"})
        self.assertIn("unknown parameters", ctx.exception.message)
        with self.assertRaises(Failure) as ctx:
            self.argv("module-plan", {})
        self.assertIn("required", ctx.exception.message)
        with self.assertRaises(Failure):
            self.argv("agent-status", {"thread_id": "t-1", "messages": 21})
        with self.assertRaises(Failure):
            self.argv("agent-status", {"thread_id": "t-1", "messages": "4"})
        self.assertEqual(self.argv("agent-status", {"thread_id": "t-1", "messages": 4}), ["agent", "status", "t-1", "--messages", "4"])
        with self.assertRaises(Failure):
            self.argv("agent-dispatch", {"project": "p", "title": "t", "prompt": "x", "instance": "i", "model": "m", "runtime_mode": "yolo"})
        with self.assertRaises(Failure):
            self.argv("game-install-mod", {"package": {"root": "jobs", "path": "build-1/packages/mod.ff"}, "folder": "mp_bad;rm"})
        with self.assertRaises(Failure):
            self.argv("registry-search", {"words": "hello\x00"})
        with self.assertRaises(Failure):
            self.argv("module-fetch", {"reference": "owner/thing@main"})

    def test_prompt_goes_to_a_file_and_options_repeat(self):
        argv = self.argv("agent-dispatch", {"project": "proj-1", "title": "Compose", "prompt": "run the playbook\non hello-pack",
                                            "instance": "claude_pool", "model": "claude-sonnet-5", "options": ["effort=high"]})
        self.assertEqual(argv[:8], ["agent", "dispatch", "--project", "proj-1", "--title", "Compose", "--prompt", argv[7]])
        self.assertTrue(argv[7].startswith("@"))
        self.assertEqual(Path(argv[7][1:]).read_text(encoding="utf-8"), "run the playbook\non hello-pack")
        self.assertTrue(Path(argv[7][1:]).resolve().is_relative_to(self.prompts.resolve()))
        self.assertEqual(argv[8:], ["--instance", "claude_pool", "--model", "claude-sonnet-5", "--option", "effort=high"])
        with self.assertRaises(Failure):
            self.argv("agent-send", {"thread_id": "t", "prompt": "x", "options": ["bad option"]})
        with self.assertRaises(Failure):
            self.argv("agent-dispatch", {"project": "p", "title": "t", "prompt": "x", "instance": "i", "model": "m", "options": ["effort=high;rm"]})

    def test_registry_source_is_a_library_file_or_https(self):
        (self.lib / "registry.json").write_text("{}")
        self.assertEqual(self.argv("registry-add", {"source": {"root": 0, "path": "registry.json"}}), ["registry", "add", str(self.lib / "registry.json")])
        self.assertEqual(self.argv("registry-add", {"source": "https://example.test/registry.json"}), ["registry", "add", "https://example.test/registry.json"])
        for bad in ("http://example.test/registry.json", "/etc/passwd", {"root": 0, "path": "pack/composition.json"}):
            with self.assertRaises(Failure, msg=repr(bad)):
                self.argv("registry-add", {"source": bad})


class PlaneServerFixture(DevRouteFixture):
    """A Plane over a temporary library with the examples, served on a free loopback port."""

    def setUp(self):
        super().setUp()
        import shutil

        self.lib = self.root / "lib"
        self.lib.mkdir()
        for name in ("hello-zm", "hello-zm-two", "hello-pack"):
            shutil.copytree(ROOT / "examples" / name, self.lib / name)
        shutil.copy(ROOT / "examples" / "registry.json", self.lib / "registry.json")
        self.jobs = self.root / "jobs"
        self.plane = server_module.Plane([self.lib], self.jobs)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), server_module.make_handler(self.plane))
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"

    def call(self, path, body=None, token=None, host=None, origin=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.origin + path, data=data, method="POST" if data is not None else "GET")
        req.add_header("X-Plane-Token", self.plane.token if token is None else token)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if host:
            req.add_header("Host", host)
        if origin:
            req.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def finish(self, run_id, seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            _, body = self.call("/api/runs/" + run_id)
            if body["run"]["status"] != "running":
                return body["run"]
            time.sleep(0.2)
        self.fail("run did not finish")


class PlaneServerTests(PlaneServerFixture):
    def test_guards_token_host_and_origin(self):
        self.assertEqual(self.call("/api/state", token="")[0], 401)
        self.assertEqual(self.call("/api/state", token="x" * 43)[0], 401)
        self.assertEqual(self.call("/api/state", host="evil.example:80")[0], 403)
        self.assertEqual(self.call("/api/state", origin="http://evil.example")[0], 403)
        self.assertEqual(self.call("/api/state", origin=self.origin)[0], 200)
        self.assertEqual(self.call("/api/state", host="localhost:1")[0], 200)
        status, body = self.call("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(body["library"], [str(self.lib.resolve())])
        self.assertFalse(body["running"])
        # The page and its assets need no token (they hold none); the API refuses without it.
        with urllib.request.urlopen(self.origin + "/", timeout=5) as response:
            page = response.read().decode()
            self.assertIn("default-src 'none'", response.getheader("Content-Security-Policy"))
        self.assertIn("pat control plane", page)
        self.assertNotIn(self.plane.token, page)
        with urllib.request.urlopen(self.origin + "/plane.js", timeout=5) as response:
            self.assertIn("javascript", response.getheader("Content-Type"))
        self.assertEqual(self.call("/api/nothing")[0], 404)
        self.assertEqual(self.call("/api/run", {"action": "module-plan"}, token="")[0], 401)

    def test_library_and_actions(self):
        status, body = self.call("/api/library")
        self.assertEqual(status, 200)
        root = body["roots"][0]
        self.assertEqual(sorted(m["id"] for m in root["modules"]), ["hello_zm", "round_announcer"])
        self.assertEqual([c["name"] for c in root["compositions"]], ["stock_hello_pack"])
        self.assertEqual(root["modules"][0]["payload"], "recipe")
        status, body = self.call("/api/actions")
        self.assertEqual([a["id"] for a in body["actions"]], [a.id for a in ACTIONS])

    def test_plan_build_verify_and_the_receipt_index(self):
        status, body = self.call("/api/run", {"action": "module-plan", "args": {"composition": {"root": 0, "path": "hello-pack/composition.json"}}})
        self.assertEqual(status, 202, body)
        run = self.finish(body["run"]["run_id"])
        self.assertEqual(run["status"], "finished")
        self.assertEqual(run["exit_code"], 0)
        self.assertTrue(run["result"]["ok"], run)
        self.assertEqual([m["id"] for m in run["result"]["result"]["modules"]], ["hello_zm", "round_announcer"])
        self.assertEqual(run["argv"][-3:], ["--output", str(self.jobs / "module-plan-0001"), "--json"])
        self.assertTrue((self.jobs / "module-plan-0001" / "receipt.json").is_file())
        self.assertTrue((self.jobs / "plane-runs" / f"{run['run_id']}.json").is_file())

        status, body = self.call("/api/run", {"action": "module-build", "args": {"composition": {"root": 0, "path": "hello-pack/composition.json"}}})
        run = self.finish(body["run"]["run_id"])
        self.assertTrue(run["result"]["ok"], run)
        self.assertEqual(run["result"]["result"]["mod_ff"], "packages/mod.ff")
        build_dir = Path(run["output"])
        self.assertTrue((build_dir / "packages" / "mod.ff").is_file())

        status, body = self.call("/api/run", {"action": "project-verify", "args": {"receipt": {"root": "jobs", "path": build_dir.name + "/receipt.json"}, "inputs": True}})
        run = self.finish(body["run"]["run_id"])
        self.assertTrue(run["result"]["ok"], run)

        status, body = self.call("/api/jobs")
        rows = {r["directory"]: r for r in body["runs"]}
        self.assertEqual(rows[build_dir.name]["status"], "succeeded")
        self.assertEqual(rows[build_dir.name]["mod_ff"], "packages/mod.ff")
        self.assertEqual(rows["module-plan-0001"]["command"], "module plan")
        status, body = self.call("/api/runs")
        self.assertEqual([r["number"] for r in body["runs"]], [3, 2, 1])
        self.assertFalse(body["running"])

    def test_one_run_at_a_time_and_a_failed_child_is_recorded(self):
        args = {"composition": {"root": 0, "path": "hello-pack/composition.json"}}
        status, first = self.call("/api/run", {"action": "module-build", "args": args})
        self.assertEqual(status, 202)
        status, second = self.call("/api/run", {"action": "module-plan", "args": args})
        self.assertEqual(status, 409)
        self.assertEqual(second["error_code"], "busy")
        self.finish(first["run"]["run_id"])
        # A child that fails structurally is a finished run with the child's error, not a server error.
        status, body = self.call("/api/run", {"action": "game-install-mod", "confirmed": True,
                                              "args": {"package": {"root": "jobs", "path": first["run"]["output"].rsplit("/", 1)[-1] + "/packages/mod.ff"}, "folder": "stock_hello_pack"}})
        self.assertEqual(status, 202, body)
        run = self.finish(body["run"]["run_id"])
        self.assertEqual(run["status"], "finished")
        self.assertEqual(run["exit_code"], 1)
        self.assertEqual(run["result"]["error_code"], "config_missing", "no storage is configured in this fixture")

    def test_refusals_before_any_child_starts(self):
        args = {"composition": {"root": 0, "path": "hello-pack/composition.json"}}
        cases = [
            ({"action": "module-plan", "args": {"composition": {"root": 0, "path": "../hello-pack/composition.json"}}}, 400, "input_invalid"),
            ({"action": "module-plan", "args": {**args, "output": "/tmp/x"}}, 400, "input_invalid"),
            ({"action": "no-such-action", "args": {}}, 400, "input_invalid"),
            ({"action": "game-install-mod", "args": {"package": {"root": 0, "path": "hello-zm/module.json"}, "folder": "x"}}, 400, "input_invalid"),
            ({"action": "game-launch", "args": {}, "confirmed": True}, 409, "unsupported_platform"),
            ({"action": "agent-interrupt", "args": {"thread_id": "t-1"}}, 400, "input_invalid"),  # not confirmed
            ({"action": "agent-dispatch", "confirmed": True, "args": {"project": "p", "title": "t", "prompt": "x", "instance": "i"}}, 400, "input_invalid"),
        ]
        if os.name == "nt":
            cases = [c for c in cases if c[0]["action"] != "game-launch"]
        for body, status, code in cases:
            got_status, got = self.call("/api/run", body)
            self.assertEqual((got_status, got.get("error_code")), (status, code), (body, got))
        self.assertEqual(self.call("/api/runs")[1]["runs"], [], "nothing was started")
        self.assertFalse((self.jobs / "plane-prompts").exists(), "no prompt file for a refused dispatch")
        too_big = self.call("/api/run", {"action": "module-plan", "args": {"composition": {"root": 0, "path": "x" * 5000}}})
        self.assertEqual(too_big[0], 400)

    def test_registry_actions_run_as_children_with_the_words_split(self):
        status, body = self.call("/api/run", {"action": "registry-add", "args": {"source": {"root": 0, "path": "registry.json"}}})
        run = self.finish(body["run"]["run_id"])
        self.assertTrue(run["result"]["ok"], run)
        self.assertEqual(run["result"]["result"]["entries"], 3)
        status, body = self.call("/api/run", {"action": "registry-search", "args": {"words": "hello round", "category": "scripts"}})
        run = self.finish(body["run"]["run_id"])
        self.assertEqual(run["argv"], ["registry", "search", "hello", "round", "--category", "scripts", "--json"])
        self.assertTrue(run["result"]["ok"], run)

    def test_private_seed_shows_package_absent(self):
        module = self.lib / "secret"
        module.mkdir()
        (module / "module.json").write_text(json.dumps({"schema": 1, "id": "secret", "version": "1", "seed": "seed.json",
                                                         "bases": ["stock"], "maps": ["zm_transit"], "distribution": "private"}))
        (module / "seed.json").write_text(json.dumps({"schema": 1, "package": "mod.ff", "files": {"mod.ff": "0" * 64},
                                                       "roots": ["rawfile,x"], "embedded": ["rawfile,x"], "referenced": []}))
        status, body = self.call("/api/library")
        row = next(m for m in body["roots"][0]["modules"] if m["id"] == "secret")
        self.assertEqual(row["payload"], "seed")
        self.assertFalse(row["package_present"])
        self.assertEqual(row["distribution"], "private")


class ServeEntryTests(unittest.TestCase):
    def test_serve_validates_roots_and_stops_on_its_deadline(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "lib").mkdir()
            code, row = invoke(["plane", "serve", "--jobs", str(root / "jobs")])
            self.assertEqual(code, 2, row)
            code, row = invoke(["plane", "serve", "--library", "lib", "--jobs", str(root / "jobs")])
            self.assertEqual(row["error_code"], "input_invalid")
            code, row = invoke(["plane", "serve", "--library", str(root / "lib"), "--jobs", str(root / "lib" / "jobs")])
            self.assertEqual(row["error_code"], "input_invalid", "jobs inside a library root")
            code, row = invoke(["plane", "serve", "--library", str(root / "missing"), "--jobs", str(root / "jobs")])
            self.assertEqual(row["error_code"], "input_missing")
            announced = []
            result = server_module.serve([str(root / "lib")], str(root / "jobs"), port=0, seconds=1,
                                         announce=lambda text, **kw: announced.append(text))
            self.assertEqual(result["stopped"], "deadline")
            self.assertEqual(result["runs"], 0)
            self.assertFalse(result["game_touched"])
            self.assertTrue(announced[0].startswith("pat plane: http://127.0.0.1:"))
            self.assertIn("#token=", announced[0])
            self.assertTrue((root / "jobs" / "plane-runs").is_dir())


if __name__ == "__main__":
    unittest.main()

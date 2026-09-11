"""``pat plane``: the typed action table, argument validation, and the loopback server driving
``pat`` children against the fake backends. No real backend, no network beyond 127.0.0.1, no game."""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request
import socket
from pathlib import Path

from plutonium_agent_toolkit.cli import JOB_GROUPS
from plutonium_agent_toolkit.core.discovery import find, routes
from plutonium_agent_toolkit.core.errors import Failure
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
            if route and route.effect == "writes-config":
                self.assertTrue(action.confirm, f"{action.id} writes the toolkit configuration and must confirm")
        self.assertTrue(all(a.screen in ("library", "pack", "install", "agent", "registry") for a in ACTIONS), "every action has a screen the page renders")

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
                    {"root": 0, "path": "C:/pack/composition.json"}, {"root": 0, "path": "//share/pack/composition.json"},
                    {"root": 0, "path": "pack/../pack/composition.json"}, {"root": 1, "path": "pack/composition.json"},
                    {"root": "jobs", "path": "build-1/receipt.json"}, "pack/composition.json", {"path": "pack/composition.json"},
                    {"root": 0, "path": "pack\\composition.json"}, {"root": True, "path": "pack/composition.json"}):
            with self.assertRaises(Failure, msg=repr(bad)) as ctx:
                self.argv("module-plan", {"composition": bad})
            self.assertEqual(ctx.exception.code, "input_invalid", repr(bad))
        with self.assertRaises(Failure) as ctx:
            self.argv("module-plan", {"composition": {"root": 0, "path": "missing/composition.json"}})
        self.assertEqual(ctx.exception.code, "input_missing")
        with self.assertRaises(Failure) as ctx:  # a lone surrogate never reaches the filesystem
            self.argv("module-plan", {"composition": {"root": 0, "path": "pack/\ud800/composition.json"}})
        self.assertEqual(ctx.exception.code, "input_invalid")
        argv = self.argv("project-verify", {"receipt": {"root": "jobs", "path": "build-1/receipt.json"}, "inputs": True})
        self.assertEqual(argv, ["project", "verify", str(self.jobs / "build-1" / "receipt.json"), "--inputs"])
        with self.assertRaises(Failure):
            self.argv("project-verify", {"receipt": {"root": 0, "path": "pack/composition.json"}})

    def test_links_and_unreadable_directories_are_refused_as_input_errors(self):
        if os.name == "nt":
            self.skipTest("symlinks and POSIX modes")
        (self.lib / "linked").symlink_to(self.lib / "pack")
        with self.assertRaises(Failure) as ctx:
            self.argv("module-plan", {"composition": {"root": 0, "path": "linked/composition.json"}})
        self.assertEqual(ctx.exception.code, "input_invalid")
        if os.geteuid() == 0:
            self.skipTest("root reads everything")
        closed = self.lib / "closed"
        (closed / "inner").mkdir(parents=True)
        (closed / "inner" / "composition.json").write_text("{}")
        closed.chmod(0)
        self.addCleanup(closed.chmod, 0o700)
        with self.assertRaises(Failure) as ctx:  # a Failure, never an OSError that drops the connection
            self.argv("module-plan", {"composition": {"root": 0, "path": "closed/inner/composition.json"}})
        self.assertIn(ctx.exception.code, ("input_invalid", "input_missing"))

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
        for folder in ("mp_bad;rm", "mp_test", ".", "..", "a/b"):
            with self.assertRaises(Failure, msg=folder):
                self.argv("game-install-mod", {"package": {"root": "jobs", "path": "build-1/packages/mod.ff"}, "folder": folder})
        with self.assertRaises(Failure):  # a lone surrogate cannot reach Popen
            self.argv("agent-dispatch", {"project": "p", "title": "bad \ud800 title", "prompt": "x", "instance": "i", "model": "m"})
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
            self.argv("agent-dispatch", {"project": "p", "title": "t", "prompt": "x", "instance": "i", "model": "m", "options": ["effort=high\x00"]})

    def test_model_slugs_and_option_values_accept_what_pat_agent_accepts(self):
        # Review finding: slugs like provider/model-name and option values with spaces or 512 characters are
        # valid for pat agent dispatch; the plane must not be stricter than the route it fronts.
        argv = self.argv("agent-dispatch", {"project": "p", "title": "t", "prompt": "x", "instance": "opencode",
                                            "model": "openai/gpt-5.1-codex (preview)", "options": ["reasoningEffort=x-high", "thinking=on; budget 8k"]})
        self.assertIn("openai/gpt-5.1-codex (preview)", argv)
        self.assertEqual(argv[-4:], ["--option", "reasoningEffort=x-high", "--option", "thinking=on; budget 8k"])
        with self.assertRaises(Failure):
            self.argv("agent-dispatch", {"project": "p", "title": "t", "prompt": "x", "instance": "i", "model": "m", "options": ["=novalue"]})
        with self.assertRaises(Failure):
            self.argv("agent-dispatch", {"project": "p", "title": "t", "prompt": "x", "instance": "i", "model": "m", "options": ["effort=" + "v" * 513]})

    def test_prompt_is_bounded_in_bytes_and_a_refused_prompt_leaves_no_file(self):
        big = "é" * 150_000  # 150k characters, 300k UTF-8 bytes: pat agent would refuse it
        with self.assertRaises(Failure):
            self.argv("agent-dispatch", {"project": "p", "title": "t", "prompt": big, "instance": "i", "model": "m"})
        with self.assertRaises(Failure):  # valid prompt, invalid later parameter: nothing written
            self.argv("agent-dispatch", {"project": "p", "title": "t", "prompt": "fine", "instance": "i", "model": "m", "runtime_mode": "nope"})
        self.assertFalse(self.prompts.exists())

    def test_registry_source_is_a_library_file_or_https(self):
        (self.lib / "registry.json").write_text("{}")
        self.assertEqual(self.argv("registry-add", {"source": {"root": 0, "path": "registry.json"}}), ["registry", "add", str(self.lib / "registry.json")])
        self.assertEqual(self.argv("registry-add", {"source": "https://example.test/registry.json"}), ["registry", "add", "https://example.test/registry.json"])
        for bad in ("http://example.test/registry.json", "/etc/passwd", {"root": 0, "path": "pack/composition.json"}):
            with self.assertRaises(Failure, msg=repr(bad)):
                self.argv("registry-add", {"source": bad})


class PlaneServerFixture(DevRouteFixture):
    """A Plane over a temporary library with the examples, served on a free loopback port."""
    max_connections = 32

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
        self.server = server_module.PlaneServer(("127.0.0.1", 0), server_module.make_handler(self.plane), max_connections=self.max_connections)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.plane.shutdown)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"

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
    def test_guards_token_host_origin_and_body(self):
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
        # A negative or absurd Content-Length is refused before any read (review finding).
        for length in ("-1", "99999999", "abc"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.putrequest("POST", "/api/run")
            conn.putheader("X-Plane-Token", self.plane.token)
            conn.putheader("Content-Length", length)
            conn.endheaders()
            response = conn.getresponse()
            self.assertEqual(response.status, 400, length)
            response.read()
            conn.close()

    def test_library_and_actions(self):
        (self.lib / "loose").mkdir()
        (self.lib / "loose" / "mod.ff").write_bytes(b"prebuilt, undeclared")
        (self.lib / "shape").mkdir()
        (self.lib / "shape" / "module.json").write_text(json.dumps({"schema": 1, "id": "Bad Id", "version": "1", "recipe": "p.json", "bases": ["stock"], "maps": ["*"]}))
        if os.name != "nt":
            (self.lib / "linked").mkdir()
            (self.lib / "linked" / "module.json").symlink_to(self.lib / "hello-zm" / "module.json")
        status, body = self.call("/api/library")
        self.assertEqual(status, 200)
        root = body["roots"][0]
        self.assertEqual(sorted(m["id"] for m in root["modules"] if "error" not in m), ["hello_zm", "round_announcer"])
        self.assertNotIn("linked", [m["path"] for m in root["modules"]], "a linked declaration is not offered")
        self.assertIn("not a module declaration", next(m for m in root["modules"] if m["path"] == "shape")["error"])
        self.assertEqual([c["name"] for c in root["compositions"]], ["stock_hello_pack"])
        self.assertEqual(root["modules"][0]["payload"], "recipe")
        self.assertEqual(root["packages"], ["loose/mod.ff"], "loose packages are listed so module declare can take them")
        self.assertFalse(body["truncated"])
        status, body = self.call("/api/actions")
        self.assertEqual([a["id"] for a in body["actions"]], [a.id for a in ACTIONS])

    def test_catalog_is_bounded_and_tolerates_bad_manifests(self):
        for i in range(5):
            d = self.lib / f"odd{i}"
            d.mkdir()
            (d / "module.json").write_text(json.dumps({"schema": 1, "id": f"odd{i}", "version": "1", "seed": "seed.json",
                                                        "bases": "b2", "maps": ["zm_factory"], "tags": "scalar"}))
            (d / "seed.json").write_text("[]" if i % 2 else "not json")
        with unittest.mock.patch.object(server_module, "MAX_CATALOG_ROWS", 4):
            status, body = self.call("/api/library")
        self.assertEqual(status, 200)
        self.assertTrue(body["truncated"])
        self.assertTrue(body["roots"][0]["truncated"])
        self.assertLessEqual(len(body["roots"][0]["modules"]) + len(body["roots"][0]["compositions"]), 4)
        status, body = self.call("/api/library")
        rows = {m["id"]: m for m in body["roots"][0]["modules"]}
        self.assertEqual(rows["odd1"]["seed_error"], "seed manifest is not a JSON object")
        self.assertIsNone(rows["odd0"]["package_present"])
        self.assertEqual(rows["odd0"]["bases"], "b2", "the page normalises scalars; the server reports the file as it is")

    def test_strict_json_and_bounded_receipts(self):
        # Review findings: NaN in a declaration must not leak into the API as invalid JSON, and a
        # huge receipt.json must not be read whole.
        odd = self.lib / "nan"
        odd.mkdir()
        (odd / "module.json").write_text('{"schema": 1, "id": "nan_mod", "version": "1", "recipe": "project.json", "bases": ["stock"], "maps": ["*"], "resource_contract": {"threads": NaN}}')
        status, body = self.call("/api/library")
        self.assertEqual(status, 200)
        row = next(m for m in body["roots"][0]["modules"] if m["path"] == "nan")
        self.assertEqual(row["error"], "unreadable")
        weird = self.lib / "surrogate"
        weird.mkdir()
        (weird / "module.json").write_text('{"schema": 1, "id": "surrogate", "version": "1", "title": "bad \\ud800 title", "recipe": "project.json", "bases": ["stock"], "maps": ["*"]}')
        status, body = self.call("/api/library")
        self.assertEqual(status, 200, "an escaped lone surrogate in a declaration does not break the response")
        big = self.jobs / "huge-receipt"
        big.mkdir(parents=True)
        (big / "receipt.json").write_text("{" + " " * (300 * 1024) + "}")
        status, body = self.call("/api/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(next(r for r in body["runs"] if r["directory"] == "huge-receipt")["status"], "unreadable")
        for i in range(4):
            d = self.jobs / f"aaa-{i}"
            d.mkdir()
            (d / "receipt.json").write_text(json.dumps({"command": "x", "status": "succeeded", "started": f"2026-09-1{i}T00:00:00+00:00"}))
        with unittest.mock.patch.object(server_module, "MAX_JOB_ROWS", 2):
            status, body = self.call("/api/jobs")
        self.assertTrue(body["truncated"])
        self.assertEqual([r["directory"] for r in body["runs"]], ["aaa-3", "aaa-2"], "the newest receipts survive the bound, whatever their names")
        status, body = self.call("/api/run", {"action": "registry-search", "args": {"words": "x"}}, )
        self.assertEqual(status, 202)
        self.finish(body["run"]["run_id"])
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/run", body='{"action": "manifest", "args": {}, "confirmed": NaN}',
                     headers={"X-Plane-Token": self.plane.token, "Content-Type": "application/json"})
        response = conn.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        conn.close()

    def test_a_child_that_floods_stdout_is_stopped_and_recorded_without_a_result(self):
        with unittest.mock.patch.object(server_module, "MAX_OUTPUT", 20_000):
            status, body = self.call("/api/run", {"action": "manifest", "args": {}})
            self.assertEqual(status, 202, body)
            run = self.finish(body["run"]["run_id"])
        self.assertTrue(run["output_overflow"], run)
        self.assertIsNone(run["result"])
        self.assertGreater(run["stdout_bytes"], 20_000)
        # The bound and the count are bytes, not characters. The reader starts before the write:
        # an anonymous pipe on Windows holds 4 KiB, so writing first would block forever.
        r, w = os.pipe()
        reader = server_module._Reader(os.fdopen(r, "rb"), 10_000)
        with os.fdopen(w, "wb") as writer:
            writer.write(("é" * 6000).encode("utf-8"))  # 12000 bytes
        reader.join(5)
        self.assertFalse(reader.is_alive())
        self.assertTrue(reader.overflow)
        self.assertEqual(reader.size, 12_000)
        self.assertLessEqual(len(run["stdout_head"]), server_module.MAX_HEAD)
        status, body = self.call("/api/run", {"action": "manifest", "args": {}})
        self.assertEqual(status, 202, "the plane is usable afterwards")
        run = self.finish(body["run"]["run_id"])
        self.assertFalse(run["output_overflow"])
        self.assertTrue(run["result"]["ok"])

    def test_prompt_files_live_only_while_their_child_runs(self):
        status, body = self.call("/api/run", {"action": "agent-send", "confirmed": True, "args": {"thread_id": "t-1", "prompt": "a secret plan"}})
        self.assertEqual(status, 202, body)
        prompt_arg = next(a for a in body["run"]["argv"] if a.startswith("@"))
        run = self.finish(body["run"]["run_id"])
        self.assertEqual(run["result"]["error_code"], "config_missing", "no T3 server recorded in this fixture")
        self.assertFalse(Path(prompt_arg[1:]).exists(), "the prompt file is removed once the child ran")
        (self.jobs / "plane-prompts").mkdir(exist_ok=True)
        stray = self.jobs / "plane-prompts" / "prompt-stray.txt"
        stray.write_text("left over")
        summary = self.plane.shutdown(grace=1)
        self.assertEqual(summary["prompts_removed"], 1)
        self.assertFalse(stray.exists())

    def test_plan_build_verify_and_the_receipt_index(self):
        status, body = self.call("/api/run", {"action": "module-plan", "args": {"composition": {"root": 0, "path": "hello-pack/composition.json"}}})
        self.assertEqual(status, 202, body)
        run = self.finish(body["run"]["run_id"])
        self.assertEqual(run["status"], "finished")
        self.assertEqual(run["exit_code"], 0)
        self.assertTrue(run["result"]["ok"], run)
        self.assertEqual([m["id"] for m in run["result"]["result"]["modules"]], ["hello_zm", "round_announcer"])
        self.assertEqual(run["argv"][-3:], ["--output", str(self.jobs.resolve() / "module-plan-0001"), "--json"])
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

        # A fetched snapshot under jobs exposes its composition or declaration to the path selects.
        fetched = self.jobs / "module-fetch-0009"
        (fetched / "repository" / "pack").mkdir(parents=True)
        (fetched / "repository" / "pack" / "composition.json").write_text("{}")
        (fetched / "receipt.json").write_text(json.dumps({"schema_version": 1, "command": "module fetch", "status": "succeeded",
                                                          "started": "2026-09-11T00:00:00+00:00",
                                                          "result": {"kind": "composition", "module_dir": str(fetched / "repository" / "pack")}}))
        odd = self.jobs / "odd-receipt"
        odd.mkdir()
        (odd / "receipt.json").write_text(json.dumps({"command": "x", "status": "failed", "error": "failed", "started": "2026-09-11T00:00:00+00:00"}))
        status, body = self.call("/api/jobs")
        self.assertEqual(status, 200, body)
        rows = {r["directory"]: r for r in body["runs"]}
        self.assertEqual(rows["odd-receipt"]["error"], "failed", "a receipt whose error is not an object still lists")
        self.assertEqual(rows[build_dir.name]["status"], "succeeded")
        self.assertEqual(rows[build_dir.name]["mod_ff"], "packages/mod.ff")
        self.assertEqual(rows["module-plan-0001"]["command"], "module plan")
        self.assertEqual(rows["module-fetch-0009"]["composition"], "module-fetch-0009/repository/pack/composition.json")
        status, body = self.call("/api/runs")
        self.assertEqual([r["number"] for r in body["runs"]], [3, 2, 1])
        self.assertFalse(body["running"])

    def test_one_run_at_a_time_busy_leaves_nothing_and_a_failed_child_is_recorded(self):
        # The run lock held by a running child (taken directly here so the test has no race).
        self.assertTrue(self.plane.job_lock.acquire(blocking=False))
        try:
            status, second = self.call("/api/run", {"action": "agent-send", "confirmed": True, "args": {"thread_id": "t-1", "prompt": "x" * 1000}})
        finally:
            self.plane.job_lock.release()
        self.assertEqual(status, 409)
        self.assertEqual(second["error_code"], "busy")
        self.assertFalse((self.jobs / "plane-prompts").exists(), "a busy dispatch writes no prompt file")
        args = {"composition": {"root": 0, "path": "hello-pack/composition.json"}}
        status, first = self.call("/api/run", {"action": "module-build", "args": args})
        self.assertEqual(status, 202, first)
        self.finish(first["run"]["run_id"])
        # A child that fails structurally is a finished run with the child's error, not a server error.
        status, body = self.call("/api/run", {"action": "game-install-mod", "confirmed": True,
                                              "args": {"package": {"root": "jobs", "path": Path(first["run"]["output"]).name + "/packages/mod.ff"}, "folder": "stock_hello_pack"}})
        self.assertEqual(status, 202, body)
        run = self.finish(body["run"]["run_id"])
        self.assertEqual(run["status"], "finished")
        self.assertEqual(run["exit_code"], 1)
        self.assertEqual(run["result"]["error_code"], "config_missing", "no storage is configured in this fixture")

    def test_lock_is_released_even_when_the_run_record_cannot_be_written(self):
        args = {"composition": {"root": 0, "path": "hello-pack/composition.json"}}
        original = self.plane._record
        failures = []

        def broken(run):
            if run["status"] != "running":
                failures.append(run["run_id"])
                raise OSError("disk full")
            original(run)
        self.plane._record = broken
        status, first = self.call("/api/run", {"action": "module-plan", "args": args})
        self.assertEqual(status, 202)
        deadline = time.monotonic() + 60
        while (self.plane.job_lock.locked() or not failures) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(failures, [first["run"]["run_id"]], "the final record raised")
        self.assertFalse(self.plane.job_lock.locked(), "the lock outlives a failed record")
        self.plane._record = original
        status, second = self.call("/api/run", {"action": "module-plan", "args": args})
        self.assertEqual(status, 202, second)
        self.finish(second["run"]["run_id"])

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
        self.assertFalse(self.plane.job_lock.locked(), "a refusal releases the run lock")
        too_big = self.call("/api/run", {"action": "module-plan", "args": {"composition": {"root": 0, "path": "x" * 5000}}})
        self.assertEqual(too_big[0], 400)

    def test_registry_actions_run_as_children_with_the_words_split(self):
        status, body = self.call("/api/run", {"action": "registry-add", "args": {"source": {"root": 0, "path": "registry.json"}}})
        self.assertEqual((status, body.get("error_code")), (400, "input_invalid"), "registry add writes configuration and confirms first")
        status, body = self.call("/api/run", {"action": "registry-add", "confirmed": True, "args": {"source": {"root": 0, "path": "registry.json"}}})
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


class ConnectionBoundTests(PlaneServerFixture):
    max_connections = 1

    def test_a_half_sent_request_cannot_hold_every_worker(self):
        # Review finding: abandoned connections consumed unbounded threads. With one slot held by a
        # connection that never finishes its headers, the next connection is answered 503 at once.
        holder = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        holder.sendall(b"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1\r\n")  # no terminating blank line
        time.sleep(0.3)
        try:
            second = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            second.sendall(b"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Plane-Token: " + self.plane.token.encode() + b"\r\n\r\n")
            reply = second.recv(200)
            second.close()
            self.assertTrue(reply.startswith(b"HTTP/1.1 503"), reply)
        finally:
            holder.close()
        time.sleep(0.3)
        self.assertEqual(self.call("/api/state")[0], 200, "the slot is free once the holder is gone")
        self.assertEqual(server_module.make_handler(self.plane).timeout, server_module.CONNECTION_TIMEOUT)

    def test_refused_clients_do_not_hold_the_accept_loop(self):
        # Review finding: draining an over-capacity client on the accept thread would let a client
        # that trickles bytes delay every later connection. The refusal is answered at once and the
        # drain happens off the accept thread with a total deadline.
        holder = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        holder.sendall(b"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        time.sleep(0.3)
        tricklers = []
        try:
            for _ in range(3):
                s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
                s.sendall(b"GET /api/state HTTP/1.1\r\n")   # never finishes; keeps sending after the 503
                tricklers.append(s)
            started = time.monotonic()
            for s in tricklers:
                self.assertTrue(s.recv(200).startswith(b"HTTP/1.1 503"))
            for _ in range(4):
                for s in tricklers:
                    try:
                        s.sendall(b"X-Trickle: 1\r\n")
                    except OSError:
                        pass
                time.sleep(0.05)
            probe = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            probe.sendall(b"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Plane-Token: " + self.plane.token.encode() + b"\r\n\r\n")
            reply = probe.recv(200)
            probe.close()
            self.assertTrue(reply.startswith(b"HTTP/1.1 503"), reply)
            self.assertLess(time.monotonic() - started, server_module.REFUSE_DRAIN_SECONDS * 3,
                            "later connections are answered while earlier refusals are still draining")
        finally:
            for s in tricklers:
                s.close()
            holder.close()


class SequencingTests(PlaneServerFixture):
    def test_a_failed_first_record_leaves_no_prompt_and_no_running_row(self):
        original = self.plane._record

        def broken(run):
            raise OSError("read-only jobs directory")
        self.plane._record = broken
        try:
            status, body = self.call("/api/run", {"action": "agent-send", "confirmed": True, "args": {"thread_id": "t-1", "prompt": "a secret"}})
        finally:
            self.plane._record = original
        self.assertEqual((status, body["error_code"]), (400, "operation_failed"), body)
        self.assertEqual(self.plane.run_rows(), [])
        self.assertFalse(any((self.jobs / "plane-prompts").glob("prompt-*.txt")) if (self.jobs / "plane-prompts").exists() else False)
        self.assertFalse(self.plane.job_lock.locked())

    def test_a_finished_record_means_the_next_run_can_start(self):
        # Windows CI finding: the record said finished a few milliseconds before the lock was released,
        # so the next request got busy. The lock is released before the final record is written.
        for _ in range(3):
            status, body = self.call("/api/run", {"action": "manifest", "args": {}})
            self.assertEqual(status, 202, body)
            run = self.finish(body["run"]["run_id"])
            self.assertEqual(run["status"], "finished")
            status, body = self.call("/api/run", {"action": "manifest", "args": {}})
            self.assertEqual(status, 202, body)
            self.finish(body["run"]["run_id"])
        self.assertTrue(self.plane.settled.wait(5))


class ShutdownTests(unittest.TestCase):
    def test_shutdown_stops_a_running_child_and_refuses_new_runs(self):
        # Review finding: a child must not outlive the plane. A sleeping python stands in for a build.
        with tempfile.TemporaryDirectory() as temp:
            plane = server_module.Plane([], Path(temp) / "jobs")
            process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **server_module._group_flags())
            plane.job_lock.acquire()
            plane.active = (process, server_module._job_for(process))
            started = time.monotonic()
            summary = plane.shutdown(grace=2)
            self.assertTrue(summary["child_stopped"])
            self.assertIsNotNone(process.poll(), "the child was stopped")
            self.assertLess(time.monotonic() - started, 15)
            with self.assertRaises(Failure) as ctx:
                plane.start("manifest", {}, False)
            self.assertEqual(ctx.exception.code, "busy")
            plane.job_lock.release()

    def test_a_job_handle_is_terminated_once_however_many_threads_reach_for_it(self):
        # Regression: the thread running a child and the shutdown stopping it both closed the same
        # Windows Job Object handle. The second close destroyed whatever object had taken the
        # recycled handle value over -- on the 3.13 runner, a thread's semaphore, which ended the
        # interpreter mid-suite rather than the run.
        closed, ready = [], threading.Barrier(8)
        job = server_module._Job("handle", lambda handle: closed.append(handle))

        def stop():
            ready.wait(5)
            job.close()

        threads = [threading.Thread(target=stop) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(closed, ["handle"])
        job.close()
        self.assertEqual(closed, ["handle"], "a later close is still a no-op")

    def test_a_run_accepted_just_before_shutdown_never_spawns(self):
        # Review finding: start() returned, shutdown() saw no active child, and the thread then
        # spawned one anyway. The spawn happens under the state lock and rechecks stopping.
        with tempfile.TemporaryDirectory() as temp:
            plane = server_module.Plane([], Path(temp) / "jobs")
            run = plane.start("manifest", {}, False)
            with plane.lock:  # hold the state lock so the worker cannot spawn yet
                plane.stopping = True
            # Wait for the run to be fully recorded (not only for the lock) before reading it and
            # before the temporary directory goes away: on Windows a record still being written
            # would make the cleanup fail.
            self.assertTrue(plane.settled.wait(30), "the run settled")
            record = next(r for r in plane.run_rows() if r["run_id"] == run["run_id"])
            self.assertIn(record["status"], ("stopped", "finished"))
            if record["status"] == "finished":
                self.assertEqual(record["exit_code"], 0)  # spawned before stopping was set: ran to completion, was recorded
            else:
                self.assertIn("before the child started", record["stderr_head"])


class ServeEntryTests(unittest.TestCase):
    def test_serve_validates_roots_and_stops_on_its_deadline(self):
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
            self.assertFalse(result["child_stopped_at_shutdown"])
            self.assertTrue(announced[0].startswith("pat plane: http://127.0.0.1:"))
            self.assertIn("#token=", announced[0])
            self.assertTrue((root / "jobs" / "plane-runs").is_dir())


if __name__ == "__main__":
    unittest.main()

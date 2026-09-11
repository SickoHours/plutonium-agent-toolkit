"""``pat agent``: T3 Code orchestration protocol 1 driven against a fake server in this process.

The fake mirrors the nightly's HTTP surface: the public descriptor, the bearer-gated shell and
thread snapshots, and the dispatch endpoint that validates the two command shapes the toolkit
sends. Nothing here touches a real T3 Code server.
"""
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from plutonium_agent_toolkit.cli import entry

TOKEN = "tok-" + "a" * 40
SERVER_VERSION = "0.0.41-nightly.20260910.1507"


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class FakeT3:
    """State plus a request log; one instance per test."""

    def __init__(self, protocol=1):
        self.protocol = protocol
        self.requests = []
        self.threads = {}
        self.sequence = 0
        self.projects = [{"id": "proj-1", "title": "Mods", "workspaceRoot": "/tmp/mods", "defaultModelSelection": None,
                          "scripts": [], "createdAt": "2026-09-10T00:00:00Z", "updatedAt": "2026-09-10T00:00:00Z"}]
        self.running_turn = None  # thread id whose latest turn is running

    def descriptor(self):
        row = {"environmentId": "env-1", "label": "fake", "platform": {"os": "linux", "arch": "x64", "machine": "desktop"},
               "serverVersion": SERVER_VERSION, "capabilities": {"threadSettlement": True}}
        if self.protocol == 2:
            row["orchestrationProtocolVersion"] = 2
        return row

    def shell_thread(self, thread):
        latest = None
        if thread["messages"]:
            state = "running" if self.running_turn == thread["id"] else "completed"
            latest = {"turnId": "turn-" + thread["id"], "state": state, "requestedAt": "2026-09-10T00:00:01Z",
                      "startedAt": "2026-09-10T00:00:02Z", "completedAt": None if state == "running" else "2026-09-10T00:00:09Z",
                      "assistantMessageId": None}
        return {**{k: v for k, v in thread.items() if k != "messages"}, "latestTurn": latest,
                "session": {"threadId": thread["id"], "status": "running" if latest and latest["state"] == "running" else "idle",
                            "providerName": "claudeAgent", "activeTurnId": None, "lastError": None, "updatedAt": "2026-09-10T00:00:02Z"},
                "settledAt": None, "hasPendingApprovals": False, "hasPendingUserInput": False, "latestUserMessageAt": None}

    def dispatch(self, command):
        kind = command.get("type")
        if kind == "thread.create":
            for key in ("commandId", "threadId", "projectId", "title", "modelSelection", "runtimeMode", "interactionMode", "createdAt"):
                if key not in command:
                    return 400, {"code": "invalid_request", "reason": "invalid_command", "traceId": "t"}
            if "branch" not in command or "worktreePath" not in command:
                return 400, {"code": "invalid_request", "reason": "invalid_command", "traceId": "t"}
            if command["projectId"] not in {p["id"] for p in self.projects}:
                return 400, {"code": "invalid_request", "reason": "invalid_command", "traceId": "t"}
            self.threads[command["threadId"]] = {
                "id": command["threadId"], "projectId": command["projectId"], "title": command["title"],
                "modelSelection": command["modelSelection"], "runtimeMode": command["runtimeMode"],
                "interactionMode": command["interactionMode"], "branch": command["branch"],
                "worktreePath": command["worktreePath"], "archivedAt": None, "updatedAt": command["createdAt"],
                "createdAt": command["createdAt"], "deletedAt": None, "messages": []}
        elif kind == "thread.turn.start":
            thread = self.threads.get(command.get("threadId"))
            if thread is None:
                return 400, {"code": "invalid_request", "reason": "invalid_command", "traceId": "t"}
            message = command.get("message") or {}
            if message.get("role") != "user" or "messageId" not in message or "attachments" not in message or "text" not in message:
                return 400, {"code": "invalid_request", "reason": "invalid_command", "traceId": "t"}
            thread["messages"].append({"id": message["messageId"], "role": "user", "text": message["text"], "turnId": None,
                                       "streaming": False, "createdAt": command["createdAt"], "updatedAt": command["createdAt"]})
            self.running_turn = thread["id"]
        elif kind == "thread.turn.interrupt":
            if command.get("threadId") not in self.threads:
                return 400, {"code": "invalid_request", "reason": "invalid_command", "traceId": "t"}
            self.running_turn = None
        else:
            return 400, {"code": "invalid_request", "reason": "invalid_command", "traceId": "t"}
        self.sequence += 1
        return 200, {"sequence": self.sequence}


def make_handler(fake: FakeT3):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence
            pass

        def _send(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self):
            header = self.headers.get("Authorization", "")
            if header != "Bearer " + TOKEN:
                self._send(401, {"code": "unauthorized", "traceId": "t"})
                return False
            return True

        def do_GET(self):
            fake.requests.append(("GET", self.path, self.headers.get("Authorization")))
            if self.path == "/.well-known/t3/environment":
                return self._send(200, fake.descriptor())
            if not self._authorized():
                return None
            if self.path == "/api/orchestration/shell":
                return self._send(200, {"snapshotSequence": fake.sequence, "projects": fake.projects,
                                        "threads": [fake.shell_thread(t) for t in fake.threads.values()], "updatedAt": "2026-09-10T00:00:00Z"})
            if self.path.startswith("/api/orchestration/threads/"):
                thread = fake.threads.get(self.path.rsplit("/", 1)[1])
                if thread is None:
                    return self._send(404, {"code": "not_found", "reason": "thread_not_found", "traceId": "t"})
                row = fake.shell_thread(thread)
                row["messages"] = thread["messages"]
                return self._send(200, {"snapshotSequence": fake.sequence, "thread": row})
            return self._send(404, {"code": "not_found", "traceId": "t"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            fake.requests.append(("POST", self.path, body))
            if not self._authorized():
                return None
            if self.path != "/api/orchestration/dispatch":
                return self._send(404, {"code": "not_found", "traceId": "t"})
            if fake.protocol == 2:
                return self._send(404, {"code": "not_found", "traceId": "t"})
            status, row = fake.dispatch(body)
            return self._send(status, row)

    return Handler


class AgentFixture(unittest.TestCase):
    protocol = 1

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.saved = {k: os.environ.get(k) for k in ("PAT_HOME", "T3CODE_HOME")}
        os.environ["PAT_HOME"] = str(self.root / "home")
        os.environ["T3CODE_HOME"] = str(self.root / "t3")
        self.addCleanup(self._restore)
        self.fake = FakeT3(protocol=self.protocol)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.fake))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        userdata = self.root / "t3" / "userdata"
        userdata.mkdir(parents=True)
        (userdata / "server-runtime.json").write_text(json.dumps(
            {"version": 1, "pid": os.getpid(), "host": "127.0.0.1", "port": self.server.server_address[1],
             "origin": self.origin, "startedAt": "2026-09-10T00:00:00Z"}))
        (userdata / "settings.json").write_text(json.dumps({"providers": {}, "providerInstances": {
            "claude_pool": {"driver": "claudeAgent", "displayName": "Claude pool", "enabled": True, "config": {}},
            "opencode": {"driver": "opencode", "enabled": True, "config": {}}}}))
        (userdata / "model-manifest.json").write_text(json.dumps({"fetchedAtMs": 1, "manifest": {
            "version": 1, "updatedAt": "2026-09-04T19:10:48Z", "currentModels": {"claudeAgent": ["claude-sonnet-5"]},
            "providers": {"claudeAgent": {"defaults": {"chat": "claude-sonnet-5"}, "profiles": {"sonnet-5": {"capabilities": {
                "optionDescriptors": [{"id": "effort", "label": "Reasoning", "type": "select", "options": [
                    {"id": "low", "label": "Low"}, {"id": "high", "label": "High", "isDefault": True}]}]}}},
                "models": [{"slug": "claude-sonnet-5", "name": "Claude Sonnet 5", "status": "current", "profile": "sonnet-5"}]}}}}))

    def _restore(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def configure_token(self, token=TOKEN):
        code, row = invoke(["configure", "--t3-bearer-token", token])
        self.assertEqual(code, 0, row)


class ProbeAndModelsTests(AgentFixture):
    def test_probe_reads_runtime_state_and_descriptor_without_a_token(self):
        code, row = invoke(["agent", "probe"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["server_version"], SERVER_VERSION)
        self.assertEqual(result["environment_id"], "env-1")
        self.assertEqual(result["orchestration_protocol"], 1)
        self.assertTrue(result["drivable"])
        self.assertEqual(result["runtime_state"]["origin"], self.origin)
        self.assertEqual(result["thread_url"], self.origin + "/env-1/<thread-id>")
        self.assertEqual([r for r in self.fake.requests if r[0] == "GET"][0][2], None, "probe sends no Authorization header")

    def test_probe_with_explicit_origin_and_bad_origin(self):
        code, row = invoke(["agent", "probe", "--origin", self.origin])
        self.assertEqual(code, 0, row)
        self.assertNotIn("runtime_state", row["result"])
        code, row = invoke(["agent", "probe", "--origin", "http://127.0.0.1:1/with/path"])
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = invoke(["agent", "probe", "--origin", "http://127.0.0.1:1"])
        self.assertEqual(row["error_code"], "backend_failed")

    def test_probe_without_a_server_recorded(self):
        (self.root / "t3" / "userdata" / "server-runtime.json").unlink()
        code, row = invoke(["agent", "probe"])
        self.assertEqual(row["error_code"], "config_missing")

    def test_models_lists_instances_models_and_option_choices(self):
        code, row = invoke(["agent", "models"])
        self.assertEqual(code, 0, row)
        instances = {i["instance_id"]: i for i in row["result"]["instances"]}
        self.assertEqual(set(instances), {"claude_pool", "opencode"})
        claude = instances["claude_pool"]
        self.assertEqual(claude["driver"], "claudeAgent")
        self.assertEqual(claude["default_chat_model"], "claude-sonnet-5")
        self.assertEqual(claude["models"][0]["slug"], "claude-sonnet-5")
        effort = claude["models"][0]["options"][0]
        self.assertEqual(effort["id"], "effort")
        self.assertEqual([c["id"] for c in effort["choices"]], ["low", "high"])
        self.assertTrue(effort["choices"][1]["default"])
        self.assertEqual(instances["opencode"]["models"], [], "a driver without a manifest entry lists no models")

    def test_models_with_explicit_home_and_missing_settings(self):
        code, row = invoke(["agent", "models", "--home", str(self.root / "t3")])
        self.assertEqual(code, 0, row)
        code, row = invoke(["agent", "models", "--home", str(self.root / "elsewhere")])
        self.assertEqual(row["error_code"], "config_missing")
        code, row = invoke(["agent", "models", "--home", "relative"])
        self.assertEqual(code, 2)


class TokenTests(AgentFixture):
    def test_routes_needing_a_token_refuse_without_one(self):
        code, row = invoke(["agent", "hosts"])
        self.assertEqual(row["error_code"], "config_missing")
        self.assertIn("t3 auth session issue", row["hint"])
        self.assertEqual([r for r in self.fake.requests if r[0] == "POST"], [], "nothing dispatched without a token")

    def test_token_is_stored_as_a_secret_and_redacted_by_doctor(self):
        code, row = invoke(["configure", "--t3-bearer-token", "with space"])
        self.assertEqual(row["error_code"], "config_invalid")
        self.configure_token()
        code, row = invoke(["doctor"])
        self.assertEqual(row["result"]["configuration"]["config"]["t3_bearer_token"], "<set>")
        self.assertNotIn(TOKEN, json.dumps(row))

    def test_wrong_token_maps_401_to_config_invalid(self):
        self.configure_token("tok-wrong")
        code, row = invoke(["agent", "hosts"])
        self.assertEqual(row["error_code"], "config_invalid")
        self.assertIn("401", row["message"])


class DispatchTests(AgentFixture):
    def dispatch(self, *extra):
        return invoke(["agent", "dispatch", "--project", "proj-1", "--title", "Build the hello pack",
                       "--prompt", "Follow docs/playbooks/compose-a-pack.md for examples/hello-pack.",
                       "--instance", "claude_pool", "--model", "claude-sonnet-5", "--option", "effort=high", *extra])

    def test_dispatch_creates_a_thread_then_starts_the_turn_with_the_chosen_model(self):
        self.configure_token()
        code, row = self.dispatch("--worktree", str(self.root), "--branch", "agent/hello")
        self.assertEqual(code, 0, row)
        result = row["result"]
        posts = [r[2] for r in self.fake.requests if r[0] == "POST"]
        self.assertEqual([p["type"] for p in posts], ["thread.create", "thread.turn.start"])
        create, start = posts
        self.assertEqual(create["threadId"], result["thread_id"])
        self.assertEqual(create["modelSelection"], {"instanceId": "claude_pool", "model": "claude-sonnet-5",
                                                    "options": [{"id": "effort", "value": "high"}]})
        self.assertEqual(create["runtimeMode"], "full-access")
        self.assertEqual(create["worktreePath"], str(self.root))
        self.assertEqual(create["branch"], "agent/hello")
        self.assertEqual(start["message"]["role"], "user")
        self.assertEqual(start["message"]["attachments"], [])
        self.assertEqual(start["modelSelection"], create["modelSelection"])
        self.assertEqual([c["sequence"] for c in result["commands"]], [1, 2])
        self.assertEqual(result["thread_url"], f"{self.origin}/env-1/{result['thread_id']}")
        self.assertFalse(result["game_touched"])

    def test_dispatch_reads_the_prompt_from_a_file_and_bounds_it(self):
        self.configure_token()
        prompt = self.root / "prompt.md"
        prompt.write_text("Do the thing.\n")
        code, row = invoke(["agent", "dispatch", "--project", "proj-1", "--title", "t", "--prompt", "@" + str(prompt),
                            "--instance", "claude_pool", "--model", "claude-sonnet-5"])
        self.assertEqual(code, 0, row)
        start = [r[2] for r in self.fake.requests if r[0] == "POST"][1]
        self.assertEqual(start["message"]["text"], "Do the thing.\n")
        self.assertNotIn("options", start["modelSelection"], "no option sent when none chosen")
        code, row = invoke(["agent", "dispatch", "--project", "proj-1", "--title", "t", "--prompt", "@" + str(self.root / "missing.md"),
                            "--instance", "claude_pool", "--model", "claude-sonnet-5"])
        self.assertEqual(row["error_code"], "input_missing")

    def test_dispatch_validation_before_any_request(self):
        self.configure_token()
        for extra, code_expected in ((["--option", "effort"], "input_invalid"), (["--worktree", "relative"], "input_invalid")):
            code, row = invoke(["agent", "dispatch", "--project", "proj-1", "--title", "t", "--prompt", "p",
                                "--instance", "claude_pool", "--model", "claude-sonnet-5", *extra])
            self.assertEqual(row["error_code"], code_expected, extra)
        self.assertEqual([r for r in self.fake.requests if r[0] == "POST"], [])
        code, row = invoke(["agent", "dispatch", "--project", "nope", "--title", "t", "--prompt", "p",
                            "--instance", "claude_pool", "--model", "claude-sonnet-5"])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("thread.create", row["message"])

    def test_dispatch_never_picks_a_model(self):
        code, row = invoke(["agent", "dispatch", "--project", "proj-1", "--title", "t", "--prompt", "p"])
        self.assertEqual(code, 2)
        self.assertEqual(row["error_code"], "invalid_arguments")

    def test_status_send_and_interrupt_follow_the_thread(self):
        self.configure_token()
        code, row = self.dispatch()
        thread_id = row["result"]["thread_id"]
        code, row = invoke(["agent", "status", thread_id])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["turn_state"], "running")
        self.assertEqual(row["result"]["message_count"], 1)
        self.assertEqual(row["result"]["recent_messages"][0]["role"], "user")
        code, row = invoke(["agent", "send", thread_id, "--prompt", "Also report the hash."])
        self.assertEqual(row["error_code"], "busy")
        self.assertEqual(len([r for r in self.fake.requests if r[0] == "POST"]), 2, "busy refusal sent nothing")
        code, row = invoke(["agent", "send", thread_id, "--prompt", "Also report the hash.", "--queue"])
        self.assertEqual(code, 0, row)
        self.assertTrue(row["result"]["queued_behind_running_turn"])
        code, row = invoke(["agent", "interrupt", thread_id])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["turn_state_before"], "running")
        code, row = invoke(["agent", "status", thread_id, "--messages", "20"])
        self.assertEqual(row["result"]["turn_state"], "completed")
        self.assertEqual(row["result"]["message_count"], 2)
        code, row = invoke(["agent", "send", thread_id, "--prompt", "Now it is idle."])
        self.assertEqual(code, 0, row)
        self.assertFalse(row["result"]["queued_behind_running_turn"])
        code, row = invoke(["agent", "status", "does-not-exist"])
        self.assertEqual(row["error_code"], "input_missing")
        code, row = invoke(["agent", "hosts"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["projects"][0]["id"], "proj-1")
        self.assertEqual(row["result"]["threads"][0]["id"], thread_id)


class ProtocolTwoTests(AgentFixture):
    protocol = 2

    def test_a_v2_host_is_reported_and_refused_before_any_command(self):
        code, row = invoke(["agent", "probe"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["orchestration_protocol"], 2)
        self.assertFalse(row["result"]["drivable"])
        self.configure_token()
        code, row = invoke(["agent", "dispatch", "--project", "proj-1", "--title", "t", "--prompt", "p",
                            "--instance", "claude_pool", "--model", "claude-sonnet-5"])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "not_implemented")
        self.assertEqual(row["details"]["probe"]["orchestration_protocol"], 2)
        self.assertEqual([r for r in self.fake.requests if r[0] == "POST"], [], "nothing dispatched to a V2 host")


if __name__ == "__main__":
    unittest.main()


class ReviewRegressionTests(AgentFixture):
    def test_token_goes_only_to_loopback_or_the_recorded_origin(self):
        self.configure_token()
        # A remote origin never receives the bearer, even with --origin given explicitly.
        code, row = invoke(["agent", "hosts", "--origin", "https://attacker.example"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("bearer", row["message"])
        self.assertEqual([r for r in self.fake.requests if r[2]], [], "no request carried an Authorization header")
        # probe is public and may go anywhere reachable
        code, row = invoke(["agent", "probe", "--origin", self.origin])
        self.assertEqual(code, 0, row)
        # loopback works with an explicit origin too
        code, row = invoke(["agent", "hosts", "--origin", self.origin])
        self.assertEqual(code, 0, row)

    def test_origin_normalisation_keeps_ipv6_brackets_and_explicit_ports(self):
        from plutonium_agent_toolkit.agent import t3

        self.assertEqual(t3.normalize_origin("http://[::1]:3773"), "http://[::1]:3773")
        self.assertEqual(t3.normalize_origin("http://127.0.0.1:0"), "http://127.0.0.1:0")
        self.assertEqual(t3.normalize_origin("127.0.0.1:3773/"), "http://127.0.0.1:3773")
        self.assertTrue(t3.is_loopback("http://[::1]:3773"))
        self.assertTrue(t3.is_loopback("http://localhost:3773"))
        self.assertFalse(t3.is_loopback("https://attacker.example"))
        for bad in ("http://127.0.0.1:99999", "http://127.0.0.1/path", "ftp://127.0.0.1", "http://127.0.0.1:3773?x=1"):
            with self.assertRaises(Exception, msg=bad):
                t3.normalize_origin(bad)

    def test_config_file_holding_the_token_is_owner_only(self):
        if os.name == "nt":
            self.skipTest("POSIX permissions")
        import stat
        self.configure_token()
        mode = stat.S_IMODE((self.root / "home" / "config.json").stat().st_mode)
        self.assertEqual(mode, 0o600, oct(mode))

    def test_models_refuses_a_malformed_provider_instances_value(self):
        settings = self.root / "t3" / "userdata" / "settings.json"
        settings.write_text(json.dumps({"providers": {}, "providerInstances": []}))
        code, row = invoke(["agent", "models"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")

    def test_dispatch_failure_on_create_carries_identifiers(self):
        self.configure_token()
        self.fake.projects = []  # thread.create is refused with 400 for an unknown project
        code, row = invoke(["agent", "dispatch", "--project", "proj-1", "--title", "t", "--prompt", "p",
                            "--instance", "claude_pool", "--model", "claude-sonnet-5"])
        self.assertEqual(code, 1, row)
        self.assertIn("thread_id", row["details"])
        self.assertIn("command_id", row["details"])

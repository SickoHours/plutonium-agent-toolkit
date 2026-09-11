"""``pat mcp``: the control plane's typed actions as Model Context Protocol tools.

The bridge is driven in process over string streams, and once as a real child process over pipes,
so the stdio contract (protocol on stdout, everything else on stderr) is exercised for real. No
network, no game: the actions that would touch one are refused here as they are on the page.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from plutonium_agent_toolkit.cli import entry
from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.mcp import server as mcp
from plutonium_agent_toolkit.plane import server as plane_server
from plutonium_agent_toolkit.plane.actions import BY_ID
from tests.test_dev_routes import DevRouteFixture

ROOT = Path(__file__).resolve().parents[1]


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class ToolDefinitionTests(unittest.TestCase):
    def test_every_action_is_a_tool_with_a_well_formed_schema(self):
        code, row = invoke(["mcp", "tools"])
        self.assertEqual(code, 0, row)
        tools = row["result"]["tools"]
        self.assertEqual(row["result"]["count"], len(tools))
        names = [t["name"] for t in tools]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(BY_ID) | set(mcp.LOCAL_TOOLS))
        for tool in tools:
            self.assertRegex(tool["name"], r"^[a-zA-Z0-9_-]{1,64}$", tool["name"])
            self.assertTrue(tool["description"].strip())
            schema = tool["inputSchema"]
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"], tool["name"])
            self.assertLessEqual(set(schema.get("required", [])), set(schema["properties"]), tool["name"])
        by_name = {t["name"]: t for t in tools}
        # A state-changing action asks for confirmation in its own schema, not only in prose.
        for name, action in BY_ID.items():
            if action.confirm:
                self.assertIn("confirmed", by_name[name]["inputSchema"]["required"], name)
                self.assertIn("Changes state", by_name[name]["description"], name)
            else:
                self.assertNotIn("confirmed", by_name[name]["inputSchema"]["properties"], name)
        # Paths are the structured root-and-relative shape, never a free string.
        composition = by_name["module-plan"]["inputSchema"]["properties"]["composition"]
        self.assertEqual(composition["type"], "object")
        self.assertEqual(sorted(composition["required"]), ["path", "root"])
        self.assertFalse(composition["additionalProperties"])
        # The route's effect and this host's availability are visible before a call.
        self.assertIn("Effect: inert", by_name["manifest"]["description"])
        if os.name != "nt":
            self.assertIn("NOT AVAILABLE on this host", by_name["game-select-mod"]["description"])

    def test_the_tools_route_serves_nothing_and_is_registered_as_inert(self):
        code, row = invoke(["describe", "mcp", "tools"])
        self.assertEqual(row["result"]["effect"], "inert")
        code, row = invoke(["describe", "mcp", "serve"])
        self.assertEqual(row["result"]["effect"], "serves-stdio")
        self.assertIn("confirmed: true", row["result"]["notes"])
        code, row = invoke(["manifest"])
        by_id = {r["id"]: r for r in row["result"]["routes"]}
        self.assertEqual(by_id["mcp.serve"]["status"], "implemented")
        self.assertIn("serves-stdio", row["result"]["effects"])


class BridgeFixture(DevRouteFixture):
    """A bridge over a temporary library holding the bundled examples."""

    def setUp(self):
        super().setUp()
        import shutil

        self.lib = self.root / "lib"
        self.lib.mkdir()
        for name in ("hello-zm", "hello-zm-two", "hello-pack"):
            shutil.copytree(ROOT / "examples" / name, self.lib / name)
        self.jobs = self.root / "jobs"
        self.plane = plane_server.Plane([self.lib], self.jobs)
        self.addCleanup(self.plane.shutdown)
        self.bridge = mcp.Bridge(self.plane)
        self.next_id = 0

    def rpc(self, method, params=None, notification=False):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            self.next_id += 1
            message["id"] = self.next_id
        return self.bridge.handle(message)

    def start(self, protocol="2025-06-18"):
        answer = self.rpc("initialize", {"protocolVersion": protocol, "capabilities": {},
                                         "clientInfo": {"name": "test-harness", "version": "1"}})
        self.assertIsNone(self.rpc("notifications/initialized", notification=True))
        return answer

    def call_tool(self, name, arguments=None):
        answer = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        result = answer["result"]
        self.assertEqual(result["content"][0]["type"], "text")
        return result["isError"], json.loads(result["content"][0]["text"])


class HandshakeTests(BridgeFixture):
    def test_initialize_negotiates_and_gates_the_other_methods(self):
        answer = self.start()
        result = answer["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "plutonium-agent-toolkit")
        self.assertEqual(result["capabilities"]["tools"], {"listChanged": False})
        self.assertIn("confirmed: true", result["instructions"])
        self.assertEqual(self.bridge.client["name"], "test-harness")
        self.assertEqual(self.rpc("ping")["result"], {})
        # A version the bridge does not implement gets the newest it does, per the protocol.
        fresh = mcp.Bridge(self.plane)
        answer = fresh.handle({"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual(answer["result"]["protocolVersion"], mcp.SUPPORTED_PROTOCOLS[0])
        # Before initialize, tools are refused; unknown methods are refused after it.
        cold = mcp.Bridge(self.plane)
        self.assertEqual(cold.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["error"]["code"], -32002)
        self.assertEqual(self.rpc("tools/there_is_no_such_method")["error"]["code"], -32601)
        self.assertIsNone(self.rpc("notifications/something_unknown", notification=True))
        self.assertEqual(self.rpc("tools/call", "not an object")["error"]["code"], -32602)

    def test_tools_list_matches_the_action_table(self):
        self.start()
        tools = self.rpc("tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, set(BY_ID) | set(mcp.LOCAL_TOOLS))


class ToolCallTests(BridgeFixture):
    def test_a_read_runs_a_child_and_returns_its_document(self):
        self.start()
        is_error, payload = self.call_tool("manifest")
        self.assertFalse(is_error, payload)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["run"]["route"], "manifest")
        self.assertEqual(payload["run"]["argv"], ["manifest", "--json"])
        self.assertEqual(payload["run"]["status"], "finished")
        self.assertIn("mcp.serve", [r["id"] for r in payload["result"]["result"]["routes"]])

    def test_a_job_writes_a_receipt_and_the_run_is_listed(self):
        self.start()
        is_error, payload = self.call_tool("module-plan", {"composition": {"root": 0, "path": "hello-pack/composition.json"}})
        self.assertFalse(is_error, payload)
        result = payload["result"]["result"]
        self.assertEqual([m["id"] for m in result["modules"]], ["hello_zm", "round_announcer"])
        receipt = Path(result["output"]) / "receipt.json"
        self.assertTrue(receipt.is_file())
        self.assertEqual(json.loads(receipt.read_text())["status"], "succeeded")
        self.assertTrue(Path(result["output"]).is_relative_to(self.jobs))
        is_error, runs = self.call_tool("runs")
        self.assertFalse(is_error)
        self.assertEqual(runs["runs"][0]["action"], "module-plan")
        is_error, library = self.call_tool("library")
        self.assertFalse(is_error)
        self.assertIn("hello_zm", [m["id"] for m in library["roots"][0]["modules"]])

    def test_refusals_keep_the_protocol_and_start_nothing(self):
        self.start()
        before = len(self.plane.run_rows())
        for name, arguments, code in (
                ("no-such-tool", {}, "unknown_route"),
                ("module-plan", {}, "input_invalid"),                                     # a required parameter is missing
                ("module-plan", {"composition": {"root": 0, "path": "../outside.json"}}, "input_invalid"),
                ("module-plan", {"composition": {"root": 0, "path": "hello-pack/composition.json"}, "extra": 1}, "input_invalid"),
                ("library", {"root": 0}, "invalid_arguments"),
                ("registry-add", {"source": "https://example.test/registry.json"}, "input_invalid"),   # confirmed missing
        ):
            is_error, payload = self.call_tool(name, arguments)
            self.assertTrue(is_error, (name, payload))
            self.assertEqual(payload["error_code"], code, (name, payload))
        self.assertEqual(len(self.plane.run_rows()), before, "a refused call starts no child")
        # An action this host cannot run is refused by the same gate the page uses.
        if os.name != "nt":
            is_error, payload = self.call_tool("game-select-mod", {"folder": "hello_zm", "confirmed": True})
            self.assertTrue(is_error)
            self.assertEqual(payload["error_code"], "unsupported_platform")

    def test_a_failing_child_comes_back_as_a_structured_error(self):
        # The child runs and refuses: the bridge reports its document and its exit status, not a
        # protocol error, so the agent reads the route's own error_code.
        broken = self.lib / "broken"
        broken.mkdir()
        (broken / "composition.json").write_text(json.dumps(
            {"schema": 1, "name": "stock_broken_test", "base": "stock", "map": "zm_transit", "modules": ["../nowhere"]}))
        self.start()
        is_error, payload = self.call_tool("module-plan", {"composition": {"root": 0, "path": "broken/composition.json"}})
        self.assertTrue(is_error, payload)
        self.assertFalse(payload["result"]["ok"])
        self.assertEqual(payload["result"]["error_code"], "input_missing")
        self.assertEqual(payload["run"]["status"], "finished")
        self.assertEqual(payload["run"]["exit_code"], 1)


class PumpTests(BridgeFixture):
    def test_the_loop_answers_requests_and_ignores_notifications(self):
        lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}),
                 json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                 "",
                 "{not json}",
                 json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                 "x" * (mcp.MAX_LINE + 10),
                 json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}),
                 json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping", "params": {"pad": "y" * mcp.MAX_LINE}}),
                 json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping"})]
        sink = io.StringIO()
        summary = mcp.pump(self.bridge, io.StringIO("\n".join(lines) + "\n"), sink)
        self.assertEqual(summary["stopped"], "client")
        answers = [json.loads(line) for line in sink.getvalue().splitlines()]
        # The oversized line whose tail is drained and the oversized line that ends in a newline are
        # both refused by size, and the requests on either side of them are answered in order.
        self.assertEqual([a.get("id") for a in answers], [1, None, 2, None, 3, None, 5])
        self.assertEqual(answers[1]["error"]["code"], -32700, "a parse error is reported, the stream continues")
        self.assertEqual(answers[3]["error"]["code"], -32600, "an oversized message is refused and its tail drained")
        self.assertEqual(answers[5]["error"]["code"], -32600, "an oversized message that ends in a newline is refused too")
        self.assertEqual(len(answers[2]["result"]["tools"]), len(BY_ID) + len(mcp.LOCAL_TOOLS))
        self.assertEqual(summary["errors"], 3)

    def test_a_deadline_stops_the_loop(self):
        summary = mcp.pump(self.bridge, io.StringIO(""), io.StringIO(), deadline=0)
        self.assertEqual(summary["stopped"], "deadline")


class StdioProcessTests(BridgeFixture):
    def test_a_real_child_speaks_the_protocol_on_stdout_and_nothing_else(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
        child = subprocess.Popen([sys.executable, "-m", "plutonium_agent_toolkit", "mcp", "serve",
                                  "--library", str(self.lib), "--jobs", str(self.root / "stdio-jobs"), "--seconds", "60", "--json"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            for message in ({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                            {"jsonrpc": "2.0", "method": "notifications/initialized"},
                            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "manifest", "arguments": {}}}):
                child.stdin.write(json.dumps(message) + "\n")
            child.stdin.flush()
            handshake = json.loads(child.stdout.readline())
            self.assertEqual(handshake["result"]["serverInfo"]["version"], __import__("plutonium_agent_toolkit").__version__)
            answer = json.loads(child.stdout.readline())
            self.assertEqual(answer["id"], 2)
            self.assertFalse(answer["result"]["isError"], answer)
            child.stdin.close()
            rest = child.stdout.read()
            child.wait(timeout=60)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=30)
        # After the client disconnects, the invocation's own JSON document is the only thing left.
        self.assertEqual(child.returncode, 0, rest + child.stderr.read())
        document = json.loads(rest)
        self.assertTrue(document["ok"])
        self.assertEqual(document["command"], "mcp serve")
        self.assertEqual(document["result"]["stopped"], "client")
        self.assertEqual(document["result"]["messages"], 3)
        self.assertIsNone(document["result"]["client"], "this handshake sent no clientInfo")
        self.assertFalse(document["result"]["game_touched"])


if __name__ == "__main__":
    unittest.main()

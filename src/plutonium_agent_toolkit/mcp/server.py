"""The Model Context Protocol bridge: the control plane's typed actions as MCP tools.

One runtime, two transports. ``plane serve`` puts the actions in ``plane/actions.py`` behind a
loopback page; this module puts the same actions behind MCP on stdin and stdout, so a harness
that loads MCP servers reaches them natively. Both go through the same ``Plane``: the same
parameter validation by kind, the same refusal of an action this host cannot run, the same
confirmation gate on a state-changing action, the same one-at-a-time child process with its own
receipt under the jobs directory. Nothing here can run argv, a shell string or an absolute path,
and the bridge adds no route of its own.

Transport: JSON-RPC 2.0, one message per line, UTF-8, on stdin and stdout. ``initialize``,
``notifications/initialized``, ``ping``, ``tools/list`` and ``tools/call`` are answered; any other
method is a JSON-RPC "method not found". stdout carries only protocol; every diagnostic goes to
stderr. The server stops when the client closes stdin, when the deadline passes, or on a signal;
it then stops a running child and waits for its record.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from .. import __version__
from ..core.errors import Failure
from ..plane.actions import BY_ID, table
from ..plane.server import Plane, strict_loads, validate_roots

# MCP protocol versions this bridge implements. The client's is echoed when it is one of these,
# otherwise the newest is returned and the client decides whether to continue (the spec's rule).
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "plutonium-agent-toolkit"
MAX_LINE = 4 * 1024 * 1024      # one JSON-RPC message
MAX_RESULT = 1 * 1024 * 1024    # the text a tool result carries back
RUN_POLL = 0.05
RUN_SLACK = 30                  # seconds past an action's own timeout before the bridge gives up waiting

# Two tools read the bridge's own state instead of starting a child.
LOCAL_TOOLS = {
    "library": "Modules, compositions, seed manifests and loose packages under the library roots, read as files. Starts nothing.",
    "runs": "The runs this bridge has started, newest first, each with its action, argv, status, exit code and result. Starts nothing.",
}


# ----- tool definitions -------------------------------------------------------------------

def _schema_for(param) -> dict:
    """One parameter's JSON Schema, from the kind the control plane validates it by."""
    kind = param.kind
    if kind == "path":
        return {"type": "object", "description": param.help,
                "properties": {"root": {"description": "Index of a library root, or \"jobs\" for the jobs directory",
                                        "anyOf": [{"type": "integer", "minimum": 0}, {"const": "jobs"}]},
                               "path": {"type": "string", "description": "Forward-slash path relative to that root; no .., no links, no absolute path"}},
                "required": ["root", "path"], "additionalProperties": False}
    if kind == "flag":
        return {"type": "boolean", "description": param.help}
    if kind == "int":
        return {"type": "integer", "minimum": param.minimum, "maximum": param.maximum, "description": param.help}
    if kind == "enum":
        return {"type": "string", "enum": list(param.choices), "description": param.help}
    if kind == "options":
        return {"type": "array", "items": {"type": "string"}, "maxItems": 16,
                "description": param.help + " (each row is id=value)"}
    if kind == "registry_source":
        return {"description": param.help,
                "anyOf": [{"type": "string", "description": "An https URL"},
                          {"type": "object",
                           "properties": {"root": {"anyOf": [{"type": "integer", "minimum": 0}, {"const": "jobs"}]},
                                          "path": {"type": "string"}},
                           "required": ["root", "path"], "additionalProperties": False}]}
    return {"type": "string", "description": param.help}


def tool_definitions(platform_info: dict) -> list[dict]:
    """Every action as an MCP tool, plus the two local reads. Unavailable actions are listed with
    the reason in their description: an agent that calls one gets the same refusal the page gets,
    and hiding them would make a host's limits invisible."""
    tools = [{"name": name, "description": description,
              "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}
             for name, description in LOCAL_TOOLS.items()]
    for row in table(platform_info):
        action = BY_ID[row["id"]]
        properties, required = {}, []
        for param in action.params:
            properties[param.name] = _schema_for(param)
            if param.required:
                required.append(param.name)
        if action.confirm:
            properties["confirmed"] = {"type": "boolean",
                                       "description": "Must be true: this action changes state, and the person is expected to have seen it first"}
            required.append("confirmed")
        description = [f"{row['label']}. Runs `pat {row['route']}` as a child process"]
        description.append("and writes a receipt into a new directory under the jobs directory" if row["job"]
                           else "and returns its JSON document")
        description.append(f"Effect: {row['effect']}.")
        if row["requires_config"]:
            description.append("Needs configuration: " + ", ".join(row["requires_config"]) + ".")
        if not row["available_here"]:
            description.append("NOT AVAILABLE on this host: " + ("requires native Windows." if row["requires_windows"]
                                                                 else f"route status {row['status']}."))
        if row["confirm"]:
            description.append("Changes state: send confirmed: true.")
        if row["note"]:
            description.append(row["note"])
        tools.append({"name": row["id"], "description": " ".join(description),
                      "inputSchema": {"type": "object", "properties": properties,
                                      "required": required, "additionalProperties": False}})
    return tools


# ----- the bridge -------------------------------------------------------------------------

class Bridge:
    """A Plane plus the MCP method handlers. One instance per ``mcp serve``."""

    def __init__(self, plane: Plane):
        self.plane = plane
        self.initialized = False
        self.client = None

    # ----- tools -----
    def tools(self) -> list[dict]:
        return tool_definitions(self.plane.platform)

    def call(self, name: str, arguments: dict) -> tuple[dict, bool]:
        """(payload, is_error). The payload is the route's own JSON document, or a structured refusal."""
        if name in LOCAL_TOOLS:
            if arguments:
                raise Failure("invalid_arguments", f"{name} takes no arguments")
            return ({"library": self.plane.catalog, "runs": lambda: {"runs": self.plane.run_rows()}}[name](), False)
        if name not in BY_ID:
            raise Failure("unknown_route", f"Unknown tool {name!r}", "Call tools/list; the bridge exposes no other tool.")
        args = dict(arguments)
        confirmed = args.pop("confirmed", None)
        started = self.plane.start(name, args, confirmed is True)
        deadline = time.monotonic() + BY_ID[name].timeout + RUN_SLACK
        while time.monotonic() < deadline:
            row = next((r for r in self.plane.run_rows() if r["run_id"] == started["run_id"]), None)
            if row is not None and row["status"] != "running":
                payload = row.get("result")
                if payload is None:
                    payload = {"ok": False, "error_code": "operation_failed",
                               "message": f"{name} exited {row.get('exit_code')} without a JSON document",
                               "stdout_head": row.get("stdout_head"), "stderr_head": row.get("stderr_head")}
                return ({"run": {k: v for k, v in row.items() if k != "result"}, "result": payload},
                        not (isinstance(payload, dict) and payload.get("ok") is True))
            time.sleep(RUN_POLL)
        # The child is still running: the plane owns it and will record it; say so rather than guess.
        return ({"run": started, "result": {"ok": False, "error_code": "backend_timeout",
                                            "message": f"{name} is still running after its deadline; read the runs tool for its record"}}, True)

    # ----- JSON-RPC -----
    def handle(self, message: dict) -> dict | None:
        """One request or notification to one response, or None for a notification."""
        method, request_id = message.get("method"), message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(request_id, -32602, "params must be an object")
        if method == "initialize":
            asked = params.get("protocolVersion")
            self.client = params.get("clientInfo")
            self.initialized = True
            return _result(request_id, {
                "protocolVersion": asked if asked in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": ("Every tool is one `pat` route with typed parameters. Paths are {\"root\": <library index or "
                                 "\"jobs\">, \"path\": <relative path>}; there is no argv, shell string or absolute path. A tool that "
                                 "changes state needs confirmed: true and the person's go for that specific run. A job tool writes a "
                                 "receipt into a new directory under the jobs directory; keep the returned JSON document and its "
                                 "receipt path. Offline verified, installed, launched, playable and accepted are separate facts."),
            })
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return _result(request_id, {})
        if request_id is None:
            return None  # an unknown notification is ignored, as the protocol requires
        if not self.initialized:
            return _error(request_id, -32002, "initialize first")
        if method == "tools/list":
            return _result(request_id, {"tools": self.tools()})
        if method == "tools/call":
            name, arguments = params.get("name"), params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return _error(request_id, -32602, "tools/call takes name and an arguments object")
            try:
                payload, is_error = self.call(name, arguments)
            except Failure as exc:
                payload, is_error = exc.to_dict(), True
            except (OSError, ValueError, RuntimeError) as exc:  # never let a traceback replace the protocol
                payload, is_error = {"ok": False, "error_code": "operation_failed",
                                     "message": f"{type(exc).__name__}: {str(exc)[:400]}"}, True
            text = json.dumps(payload, indent=2, allow_nan=False)
            if len(text) > MAX_RESULT:
                text = json.dumps({"ok": False, "error_code": "output_limit",
                                   "message": f"{name} produced more than {MAX_RESULT} bytes; read its receipt or run it in a terminal"}, indent=2)
                is_error = True
            return _result(request_id, {"content": [{"type": "text", "text": text}], "isError": is_error})
        return _error(request_id, -32601, f"Unknown method {method!r}")


def _result(request_id, result: dict) -> dict | None:
    return None if request_id is None else {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code: int, message: str) -> dict | None:
    return None if request_id is None else {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


# ----- stdio loop -------------------------------------------------------------------------

def pump(bridge: Bridge, source, sink, deadline: float | None = None) -> dict:
    """Read newline-delimited JSON-RPC from source, write answers to sink. Returns a summary."""
    handled, errors = 0, 0
    while True:
        if deadline is not None and time.monotonic() > deadline:
            return {"stopped": "deadline", "messages": handled, "errors": errors}
        # Bounded read: a line longer than the bound is never held whole, and its tail is drained
        # to the next newline so the stream stays in frame.
        line = source.readline(MAX_LINE + 1)
        if not line:
            return {"stopped": "client", "messages": handled, "errors": errors}
        if len(line) > MAX_LINE and not line.endswith("\n"):
            while True:
                more = source.readline(MAX_LINE + 1)
                if not more or more.endswith("\n"):
                    break
            errors += 1
            _write(sink, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": f"message exceeds {MAX_LINE} bytes"}})
            continue
        text = line.strip()
        if not text:
            continue
        try:
            message = strict_loads(text)
            if not isinstance(message, dict):
                raise ValueError("not an object")
        except ValueError:
            errors += 1
            _write(sink, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        handled += 1
        try:
            answer = bridge.handle(message)
        except Failure as exc:
            answer = _error(message.get("id"), -32603, exc.message)
        if answer is not None:
            if answer.get("error"):
                errors += 1
            _write(sink, answer)


def _write(sink, message: dict) -> None:
    sink.write(json.dumps(message, allow_nan=False) + "\n")
    sink.flush()


def serve(library: list[str], jobs: str, seconds: int = 3600, source=None, sink=None) -> dict:
    """Serve MCP until the client closes stdin or the deadline passes. stdout is the protocol
    channel, so everything else this process prints is sent to stderr while the bridge runs."""
    roots, jobs_dir = validate_roots(library, jobs)
    plane = Plane(roots, jobs_dir)
    bridge = Bridge(plane)
    source = source or sys.stdin
    sink = sink or sys.stdout
    saved = sys.stdout
    if sink is saved:
        sys.stdout = sys.stderr  # nothing but protocol reaches the channel while the bridge runs
    started = time.monotonic()
    try:
        summary = pump(bridge, source, sink, deadline=started + seconds if seconds else None)
    finally:
        sys.stdout = saved
        stopped = plane.shutdown()
    return {"library": [str(p) for p in roots], "jobs": str(jobs_dir), "protocols": list(SUPPORTED_PROTOCOLS),
            "tools": len(bridge.tools()), "client": bridge.client, "seconds": round(time.monotonic() - started, 1),
            **summary, "child_stopped": stopped["child_stopped"], "game_touched": False,
            "verification": "the bridge started child processes with validated arguments; each kept its own JSON document and receipt"}

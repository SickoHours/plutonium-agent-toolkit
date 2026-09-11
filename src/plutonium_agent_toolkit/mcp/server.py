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
import queue
import signal
import sys
import threading
import time

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
                          {"type": "object", "description": "A registry.json under a library root (this parameter does not take the jobs directory)",
                           "properties": {"root": {"type": "integer", "minimum": 0},
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
            properties["confirmed"] = {"type": "boolean", "const": True,
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

    def call(self, name: str, arguments: dict, deadline: float | None = None) -> tuple[dict, bool]:
        """(payload, is_error). The payload is the route's own JSON document, or a structured refusal.
        ``deadline`` is the serve deadline: when it passes while a child is still running, the wait
        ends and ``serve`` stops the child through ``Plane.shutdown``, rather than outliving it."""
        if name in LOCAL_TOOLS:
            if arguments:
                raise Failure("invalid_arguments", f"{name} takes no arguments")
            return ({"library": self.plane.catalog, "runs": lambda: {"runs": self.plane.run_rows()}}[name](), False)
        if name not in BY_ID:
            raise Failure("unknown_route", f"Unknown tool {name!r}", "Call tools/list; the bridge exposes no other tool.")
        args = dict(arguments)
        confirmed = args.pop("confirmed", None)
        started = self.plane.start(name, args, confirmed is True)
        own = time.monotonic() + BY_ID[name].timeout + RUN_SLACK
        limit = own if deadline is None else min(own, deadline)
        while time.monotonic() < limit:
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
        # The child is still running. Either its own deadline passed (the plane's drain stops it) or
        # the bridge's did, and the shutdown that follows this call stops it and records it.
        stopping = deadline is not None and time.monotonic() >= deadline
        return ({"run": started,
                 "result": {"ok": False, "error_code": "cancelled" if stopping else "backend_timeout",
                            "message": (f"the bridge reached its deadline while {name} was running; it is being stopped"
                                        if stopping else
                                        f"{name} is still running after its deadline; read the runs tool for its record"),
                            "hint": "The run record under the jobs directory holds what the child finally did."}}, True)

    # ----- JSON-RPC -----
    def handle(self, message: dict, deadline: float | None = None) -> dict | None:
        """One request or notification to one response, or None for a notification."""
        if message.get("jsonrpc") != "2.0":
            return _error(message.get("id"), -32600, "every message carries jsonrpc: \"2.0\"")
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
            name, arguments = params.get("name"), params.get("arguments", {})   # an explicit non-object must reach the check below
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return _error(request_id, -32602, "tools/call takes name and an arguments object")
            try:
                payload, is_error = self.call(name, arguments, deadline)
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

_OVERSIZED = object()   # a message past the bound: its bytes are never kept, only the fact


class _Lines(threading.Thread):
    """Reads whole lines off one text stream into a queue, so the loop that answers them can also
    reach a deadline while the client is idle: a pipe read blocks until a newline or EOF, and no
    portable select works on a Windows pipe. A line past the bound is drained to the next newline
    and reported as ``_OVERSIZED``, so the stream stays in frame and nothing huge is held. Daemon:
    it dies with the process."""

    def __init__(self, source, limit: int):
        super().__init__(daemon=True)
        self.source, self.limit = source, limit
        self.lines: queue.Queue = queue.Queue(maxsize=64)
        self.start()

    def run(self) -> None:
        try:
            while True:
                line = self.source.readline(self.limit + 1)
                if not line:
                    break
                if len(line) > self.limit:
                    while not line.endswith("\n"):
                        line = self.source.readline(self.limit + 1)
                        if not line:
                            break
                    self.lines.put(_OVERSIZED)
                    continue
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self.lines.put(None)


def pump(bridge: Bridge, source, sink, deadline: float | None = None, stop: threading.Event | None = None) -> dict:
    """Answer newline-delimited JSON-RPC from source on sink until the client closes it, the
    deadline passes or ``stop`` is set. Returns a summary."""
    handled, errors = 0, 0
    reader = _Lines(source, MAX_LINE)
    while True:
        if stop is not None and stop.is_set():
            return {"stopped": "signal", "messages": handled, "errors": errors}
        if deadline is not None and time.monotonic() >= deadline:
            return {"stopped": "deadline", "messages": handled, "errors": errors}
        try:
            line = reader.lines.get(timeout=min(RUN_POLL * 4, max(0.01, deadline - time.monotonic())) if deadline else 0.2)
        except queue.Empty:
            continue
        if line is None:
            return {"stopped": "client", "messages": handled, "errors": errors}
        if line is _OVERSIZED:
            errors += 1
            _write(sink, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": f"message exceeds {MAX_LINE} characters"}})
            continue
        text = line.strip()
        if not text:
            continue
        try:
            message = strict_loads(text)
            if not isinstance(message, dict):
                raise ValueError("not an object")
        except (ValueError, RecursionError):   # nesting deep enough to exhaust the stack is a parse error too
            errors += 1
            _write(sink, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        handled += 1
        try:
            answer = bridge.handle(message, deadline)
        except Failure as exc:
            answer = _error(message.get("id"), -32603, exc.message)
        except RecursionError:
            answer = _error(message.get("id"), -32603, "the request nests too deeply to answer")
        if answer is not None:
            if answer.get("error"):
                errors += 1
            _write(sink, answer)


def _write(sink, message: dict) -> None:
    sink.write(json.dumps(message, allow_nan=False) + "\n")
    sink.flush()


def serve(library: list[str], jobs: str, seconds: int = 3600, source=None, sink=None) -> dict:
    """Serve MCP until the client closes stdin, the deadline passes or a termination signal
    arrives. stdout is the protocol channel, so everything else this process prints goes to
    stderr while the bridge runs, and a running child is always stopped and recorded on the way
    out."""
    roots, jobs_dir = validate_roots(library, jobs)
    plane = Plane(roots, jobs_dir)
    bridge = Bridge(plane)
    source = source or sys.stdin
    sink = sink or sys.stdout
    saved = sys.stdout
    if sink is saved:
        sys.stdout = sys.stderr  # nothing but protocol reaches the channel while the bridge runs
    # The protocol is UTF-8 in both directions and one message per "\n"; a console-encoded or
    # newline-translating stream would corrupt a non-ASCII prompt or split a message on Windows.
    for stream, is_real in ((source, source is sys.stdin), (sink, sink is saved)):
        if is_real:
            try:
                stream.reconfigure(encoding="utf-8", newline="\n", errors="strict")
            except (AttributeError, ValueError, OSError):
                pass
    stop = threading.Event()
    previous = {}
    for name in ("SIGTERM", "SIGINT", "SIGHUP", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            previous[number] = signal.signal(number, lambda *_: stop.set())
        except (ValueError, OSError):       # not the main thread, or not deliverable on this host
            pass
    started = time.monotonic()
    try:
        summary = pump(bridge, source, sink, deadline=started + seconds if seconds else None, stop=stop)
    finally:
        for number, handler in previous.items():
            try:
                signal.signal(number, handler)
            except (ValueError, OSError):
                pass
        sys.stdout = saved
        stopped = plane.shutdown()
    return {"library": [str(p) for p in roots], "jobs": str(jobs_dir), "protocols": list(SUPPORTED_PROTOCOLS),
            "tools": len(bridge.tools()), "client": bridge.client, "seconds": round(time.monotonic() - started, 1),
            **summary, "child_stopped": stopped["child_stopped"], "game_touched": False,
            "verification": "the bridge started child processes with validated arguments; each kept its own JSON document and receipt"}

"""Argument parsing and dispatch for ``pat mcp``."""
from __future__ import annotations

from ..core.envelope import success
from ..core.errors import INVALID_ARGUMENTS, Failure
from ..core.platform import describe


def add_parser(sub) -> None:
    p = sub.add_parser("mcp", help="Speak Model Context Protocol: the control plane's typed actions as tools for any harness")
    actions = p.add_subparsers(dest="action", required=True)
    q = actions.add_parser("tools", help="Print the tool definitions and serve nothing")
    q.add_argument("--json", action="store_true")
    q = actions.add_parser("serve", help="Serve MCP on stdin and stdout until the client disconnects")
    q.add_argument("--library", action="append", default=[], metavar="DIR",
                   help="Absolute directory holding module and composition directories; repeatable")
    q.add_argument("--jobs", required=True, metavar="DIR", help="Absolute directory where every job's output goes (created if missing)")
    q.add_argument("--seconds", type=int, default=3600, help="Stop after this many seconds (60-86400); closing stdin stops earlier")
    q.add_argument("--json", action="store_true")


def run(args, command: str) -> dict:
    from . import server

    if args.action == "tools":
        tools = server.tool_definitions(describe())
        return success(command, {"tools": tools, "count": len(tools), "protocols": list(server.SUPPORTED_PROTOCOLS),
                                 "note": "Each tool is one registered route with typed parameters; the bridge adds --output for job routes and nothing else.",
                                 "verification": "definitions only; nothing was served and no child was started"})
    if args.action == "serve":
        if not args.library:
            raise Failure(INVALID_ARGUMENTS, "Give at least one --library directory",
                          "The library holds module.json and composition.json directories")
        if not 60 <= args.seconds <= 86400:
            raise Failure(INVALID_ARGUMENTS, "--seconds is 60 to 86400")
        return success(command, server.serve(args.library, args.jobs, seconds=args.seconds))
    raise Failure(INVALID_ARGUMENTS, f"Unknown mcp action {args.action!r}")

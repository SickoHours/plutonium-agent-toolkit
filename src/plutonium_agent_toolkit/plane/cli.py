"""Argument parsing and dispatch for ``pat plane``."""
from __future__ import annotations

from ..core import platform
from ..core.envelope import success
from ..core.errors import INVALID_ARGUMENTS, Failure
from .actions import table


def add_parser(sub) -> None:
    p = sub.add_parser("plane", help="A local control plane: every button is one pat route with typed parameters")
    actions = p.add_subparsers(dest="action", required=True)
    q = actions.add_parser("actions", help="List the typed actions the page exposes")
    q.add_argument("--json", action="store_true")
    q = actions.add_parser("serve", help="Serve the page on 127.0.0.1 and run its actions as pat child processes")
    q.add_argument("--library", action="append", default=[], metavar="DIR",
                   help="Absolute directory holding module and composition directories; repeatable")
    q.add_argument("--jobs", required=True, metavar="DIR", help="Absolute directory where every job's output goes (created if missing)")
    q.add_argument("--port", type=int, default=0, help="Loopback port; 0 picks a free one")
    q.add_argument("--seconds", type=int, default=3600, help="Stop after this many seconds (1-86400); Ctrl-C stops earlier")
    q.add_argument("--json", action="store_true")


def run(args, command: str) -> dict:
    if args.action == "actions":
        return success(command, {"actions": table(platform.describe()),
                                 "note": "Each action is one registered route; the plane adds --output for job routes and nothing else."})
    if args.action == "serve":
        from . import server

        if not args.library:
            raise Failure(INVALID_ARGUMENTS, "Give at least one --library directory", "The library holds module.json and composition.json directories")
        return success(command, server.serve(args.library, args.jobs, port=args.port, seconds=args.seconds))
    raise Failure(INVALID_ARGUMENTS, f"Unknown plane action {args.action!r}")

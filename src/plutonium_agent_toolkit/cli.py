"""``pat`` command line. Every invocation prints exactly one JSON document.

    pat version
    pat manifest
    pat describe <group> <action>
    pat doctor
    pat configure --plutonium-storage-t6 <abs path> [--plutonium-launcher <abs path>] ...
    pat dev backends
    pat dev setup [--plan] [--only ID ...]
    pat <group> <action> ...          planned routes answer not_implemented

Exit statuses: 0 ok, 1 failure, 2 usage, 130 cancelled. See core/errors.py.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .core import config, platform
from .core.discovery import find, manifest, routes
from .core.envelope import emit, failure, success
from .core.errors import INVALID_ARGUMENTS, NOT_IMPLEMENTED, Failure

# Importing the route modules registers their contracts.
from .dev import routes as _dev_routes  # noqa: F401
from .game import routes as _game_routes  # noqa: F401
from .testing import routes as _testing_routes  # noqa: F401


class Parser(argparse.ArgumentParser):
    def error(self, message):  # noqa: D401 - argparse hook
        raise Failure(INVALID_ARGUMENTS, message, "Run: pat manifest --json")


def build_parser() -> Parser:
    p = Parser(prog="pat", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="group", required=True)

    for name in ("version", "manifest", "doctor"):
        q = sub.add_parser(name)
        q.add_argument("--json", action="store_true", help="Output is always JSON; flag accepted for agents")

    q = sub.add_parser("describe")
    q.add_argument("route_group")
    q.add_argument("route_action")
    q.add_argument("--json", action="store_true")

    q = sub.add_parser("configure", help="Save absolute paths under the toolkit home")
    for key, help_text in config.KNOWN_KEYS.items():
        q.add_argument("--" + key.replace("_", "-"), dest=key, help=help_text)
    q.add_argument("--json", action="store_true")

    q = sub.add_parser("dev")
    dev = q.add_subparsers(dest="action", required=True)
    b = dev.add_parser("backends")
    b.add_argument("--json", action="store_true")
    s = dev.add_parser("setup")
    s.add_argument("--plan", action="store_true", help="List pinned downloads without downloading")
    s.add_argument("--only", nargs="+", metavar="ID", help="Install only these backend IDs")
    s.add_argument("--json", action="store_true")

    # Generic planned groups accept any action so they can answer with a structured refusal.
    for group in sorted({r.group for r in routes()} - {"dev"}):
        g = sub.add_parser(group)
        g.add_argument("action")
        g.add_argument("rest", nargs=argparse.REMAINDER)
    return p


def run(argv: list[str]) -> dict:
    args = build_parser().parse_args(argv)
    group = args.group
    command = group if group in ("version", "manifest", "doctor", "describe", "configure") else f"{group} {args.action}"

    if group == "version":
        return success(command, {"version": __version__, "platform": platform.describe()})

    if group == "manifest":
        return success(command, manifest(platform.describe()))

    if group == "describe":
        route = find(args.route_group, args.route_action)
        return success(command, route.to_dict())

    if group == "doctor":
        from .dev import backends

        info = platform.describe()
        cfg_state = {}
        try:
            cfg = config.load()
            cfg_state = {"home": str(config.home()), "config": cfg, "ok": True}
        except Failure as exc:
            cfg_state = {"home": str(config.home()), "ok": False, "error": exc.to_dict()}
        result = {"platform": info, "configuration": cfg_state}
        try:
            result["backends"] = backends.doctor()
        except Failure as exc:
            result["backends"] = {"ok": False, "error": exc.to_dict()}
        result["ok"] = bool(info["supported"]) and cfg_state.get("ok", False) and result["backends"].get("ok", False)
        result["verification"] = "Presence and configuration only. Native Windows execution, game control and capture are separate facts."
        return success(command, result)

    if group == "configure":
        values = {key: getattr(args, key) for key in config.KNOWN_KEYS if getattr(args, key)}
        if not values:
            raise Failure(INVALID_ARGUMENTS, "Provide at least one configuration option", "Run: pat configure --help")
        path = config.save(values)
        return success(command, {"path": str(path), "saved": sorted(values)})

    if group == "dev" and args.action == "backends":
        from .dev import backends

        return success(command, backends.doctor() | {"pins": backends.pins()["programs"]})

    if group == "dev" and args.action == "setup":
        from .dev import backends

        if not args.plan:
            platform.require_windows("Backend setup")
        return success(command, backends.setup(only=args.only, plan=args.plan))

    route = find(group, args.action)
    raise Failure(NOT_IMPLEMENTED,
                  f"Route {route.id} is {route.status} in {__version__}; nothing was executed.",
                  f"Owner: {route.owner}. See docs/SUPPORT.md for the qualification status of every route.",
                  route=route.to_dict())


def entry(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    label = " ".join(argv[:2]) if argv else "pat"
    try:
        row = run(argv)
    except Failure as exc:
        row = failure(label, exc)
    except KeyboardInterrupt:
        row = failure(label, Failure("cancelled", "Interrupted"))
    return emit(row)


if __name__ == "__main__":
    raise SystemExit(entry())
